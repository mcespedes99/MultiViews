import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import re
import numpy
import collections
import logging
import json
import platform

#
# BrainZoneClassifier. Based on the code from https://github.com/mnarizzano/SEEGA
#

class BrainZoneClassifier(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Brain Zone Classifier"
        self.parent.categories = ["SpectralSEEG"]
        self.parent.dependencies = []
        self.parent.contributors = ["Mauricio Cespedes Tenorio (Western University)"]
        self.parent.helpText = """
    This tool localize the brain zone of a set of points choosen from a markups 
    """
        self.parent.acknowledgementText = """
This file was originally developed by G. Arnulfo (Univ. Genoa) & M. Narizzano (Univ. Genoa) as part
of the module <a href="https://github.com/mnarizzano/SEEGA">SEEG Assistant</a>.
Refer to the following publication: 
Narizzano M., Arnulfo G., Ricci S., Toselli B., Canessa A., Tisdall M., Fato M. M., 
Cardinale F. “SEEG Assistant: a 3DSlicer extension to support epilepsy surgery” 
BMC Bioinformatics (2017) doi;10.1186/s12859-017-1545-8, In Press
""" 


#
# Brain Zone DetectorWidget
#

class BrainZoneClassifierWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """
    def __init__(self, parent=None):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self._bool_plan = False
        self._Nodes_selected = False
        self.lutPath = (self.resourcePath('Data/FreeSurferColorLUT20060522.txt'),
                        self.resourcePath('Data/FreeSurferColorLUT20120827.txt'),
                        self.resourcePath('Data/FreeSurferColorLUT20150729.txt')
                        )
        print(self.lutPath)
        # (os.path.join(slicer.app.slicerHome,'NA-MIC/Extensions-30893/SlicerFreeSurfer/share/Slicer-5.0/qt-loadable-modules/FreeSurferImporter/FreeSurferColorLUT20060522.txt'), \
        #                 os.path.join(slicer.app.slicerHome,'NA-MIC/Extensions-30893/SlicerFreeSurfer/share/Slicer-5.0/qt-loadable-modules/FreeSurferImporter/FreeSurferColorLUT20120827.txt'), \
        #                 os.path.join(slicer.app.slicerHome,'NA-MIC/Extensions-30893/SlicerFreeSurfer/share/Slicer-5.0/qt-loadable-modules/FreeSurferImporter/FreeSurferColorLUT20150729.txt'))
        #                 #os.path.join(slicer.app.slicerHome,'NA-MIC/Extensions-30893/SlicerFreeSurfer/share/Slicer-5.0/qt-loadable-modules/FreeSurferImporter/Simple_surface_labels2002.txt'))

    def setup(self):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)
        # Custom toolbar for applying style
        self.modifyWindowUI()

        self._loadUI()
        self.ui.inputParcelsSelector.setMRMLScene(slicer.mrmlScene)
        self.ui.inputFiducialSelector.setMRMLScene(slicer.mrmlScene)
        self.logic = BrainZoneClassifierLogic()

        # Connections
        self._setupConnections()
    
    def _loadUI(self):
        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/BrainZoneClassifier.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        list_lut = ['FreeSurferColorLUT20060522', 'FreeSurferColorLUT20120827', 'FreeSurferColorLUT20150729']
        self.ui.planName.addItems(['Select LUT file']+list_lut)
        self.ui.planName.setCurrentIndex(self.ui.planName.findText('Select LUT file'))

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)


    def _setupConnections(self):
        # Connections
        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
        # (in the selected parameter node).
        self.ui.inputParcelsSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.inputFiducialSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.planName.connect('currentIndexChanged(int)', self.onPlanChange)
        print('ca')

        # Buttons
        self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()
    
    def cleanup(self):
        """
        Called when the application closes and the module widget is destroyed.
        """
        self.removeObservers()

    def onSceneStartClose(self, caller, event):
        """
        Called just before the scene is closed.
        """
        # Parameter node will be reset, do not use it anymore
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event):
        """
        Called just after the scene is closed.
        """
        # If this module is shown while the scene is closed then recreate a new parameter node immediately
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self):
        """
        Ensure parameter node exists and observed.
        """
        # Parameter node stores all user choices in parameter values, node selections, etc.
        # so that when the scene is saved and reloaded, these settings are restored.

        self.setParameterNode(self.logic.getParameterNode())

        # Select default input nodes if nothing is selected yet to save a few clicks for the user
        # if not self._parameterNode.GetNodeReference("InputParcel"):
        #     firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
        #     if firstVolumeNode:
        #         self._parameterNode.SetNodeReferenceID("InputParcel", firstVolumeNode.GetID())
        # if not self._parameterNode.GetNodeReference("InputFiducial"):
        #     firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
        #     if firstVolumeNode:
        #         self._parameterNode.SetNodeReferenceID("InputFiducial", firstVolumeNode.GetID())

    def setParameterNode(self, inputParameterNode):
        """
        Set and observe parameter node.
        Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
        """

        if inputParameterNode:
            self.logic.setDefaultParameters(inputParameterNode)

        # Unobserve previously selected parameter node and add an observer to the newly selected.
        # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
        # those are reflected immediately in the GUI.
        if self._parameterNode is not None:
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self._parameterNode = inputParameterNode
        if self._parameterNode is not None:
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

        # Initial GUI update
        self.updateGUIFromParameterNode()

    def updateGUIFromParameterNode(self, caller=None, event=None):
        """
        This method is called whenever parameter node is changed.
        The module GUI is updated to show the current state of the parameter node.
        """
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            print('lolo')
            return

        # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
        self._updatingGUIFromParameterNode = True

        # Update node selectors and sliders
        self.ui.inputParcelsSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputParcel"))
        self.ui.inputFiducialSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputFiducial"))
        print('aqui')

        # Update buttons states and tooltips
        inputParcel = self._parameterNode.GetNodeReference("InputParcel")
        inputFiducial = self._parameterNode.GetNodeReference("InputFiducial")
        lut_input = self.ui.planName.currentIndex
        # Condition to change button: self._bool_plan
        # Set state of apply button
        if inputParcel and inputFiducial:
            self._Nodes_selected = True
            if self._bool_plan:
                self.ui.applyButton.toolTip = "Extract positions"
                self.ui.applyButton.enabled = True
        else:
            self.ui.applyButton.toolTip = "Select the two required inputs"
            self.ui.applyButton.enabled = False
            self._Nodes_selected = False

        # if inputVolume:
        #     self.ui.outputVolumeSelector.baseName = inputVolume.GetName() + " stripped"
        #     self.ui.outputSegmentationSelector.baseName = inputVolume.GetName() + " mask"

        # All the GUI updates are done
        self._updatingGUIFromParameterNode = False
    
    def onPlanChange(self):
        """
        This method is called whenever plan object is changed.
        The module GUI is updated to show the current state of the parameter node.
        """
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            print('lolo')
            return
        # Set state of button
        if self.ui.planName.currentIndex != 0:
            self._bool_plan = True
            if self._Nodes_selected:
                self.ui.applyButton.toolTip = "Extract positions"
                self.ui.applyButton.enabled = True
        else: # The button must be disabled if the condition is not met
            self.ui.applyButton.toolTip = "Select the two required inputs"
            self.ui.applyButton.enabled = False
            self._bool_plan = False

    def updateParameterNodeFromGUI(self, caller=None, event=None):
        """
        This method is called when the user makes any change in the GUI.
        The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
        """

        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

        self._parameterNode.SetNodeReferenceID("InputParcel", self.ui.inputParcelsSelector.currentNodeID)
        self._parameterNode.SetNodeReferenceID("InputFiducial", self.ui.inputFiducialSelector.currentNodeID)
        self._parameterNode.SetParameter("LUT", self.ui.planName.currentText)

        self._parameterNode.EndModify(wasModified)

    #######################################################################################
    ###  onZoneButton                                                                 #####
    #######################################################################################
    def onApplyButton(self):
        slicer.util.showStatusMessage("START Zone Detection")
        print ("RUN Zone Detection Algorithm")
        BrainZoneClassifierLogic().runZoneDetection(self.ui.inputParcelsSelector.currentNode(), \
                                                  self.ui.inputFiducialSelector.currentNode(), \
                                                  self.lutPath, self.ui.planName.currentIndex)
        print ("END Zone Detection Algorithm")
        slicer.util.showStatusMessage("END Zone Detection")
    
    def modifyWindowUI(self):
        mainToolBar = slicer.util.findChild(slicer.util.mainWindow(), 'ModuleToolBar')
        
        moduleIcon = qt.QIcon(self.resourcePath('Icons/BrainZoneClassifier.png'))
        self.StyleAction = mainToolBar.addAction(moduleIcon, "")
        self.StyleAction.triggered.connect(self.toggleStyle)

    def toggleStyle(self):
        print('aqui slicer')
        command_to_execute = [r"C:\Program Files (x86)\Viewsonic\vCastSender\vCastSender.exe"]
        import subprocess
        subprocess.Popen(
        command_to_execute, shell = True
        )


#########################################################################################
####                                                                                 ####
#### BrainZoneClassifierLogic                                                          ####
####                                                                                 ####
#########################################################################################
class BrainZoneClassifierLogic(ScriptedLoadableModuleLogic):
    """
  """

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        # Create a Progress Bar
        self.pb = qt.QProgressBar()
    
    def setDefaultParameters(self, parameterNode):
        """
        Initialize parameter node with default settings.
        """
        if not parameterNode.GetParameter("LUT"):
            parameterNode.SetParameter("LUT", "Select LUT file")
    
    def set_colors(self, colorTableNode, lut_file):
        with open(lut_file, 'r') as f:
            raw_lut = f.readlines()

        # read and process line by line
        # label_map = pd.DataFrame(columns=['Label', 'R', 'G', 'B'])
        for line in raw_lut:
            # Remove empty spaces
            line = line.strip()
            if not (line.startswith('#') or not line):
                s = line.split()
                # info = list(filter(None, info))
                # id = int(s[0])
                info_s = {
                    'id': int(s[0]),
                    'Label': s[1],
                    'R': int(s[2]),
                    'G': int(s[3]),
                    'B': int(s[4]),
                    'A': int(s[5])
                }
                colorTableNode.SetColor(int(s[0]), s[1], int(s[2]), int(s[3]), int(s[4]), int(s[5]))
                # info_s['A'] = 0 if (info_s['R']==0 & info_s['G']==0 & info_s['B']==0) else 255
            #     info_s = pd.DataFrame(info_s, index=[id])
            #     label_map = pd.concat([label_map,info_s], axis=0)
            # label_map[['R','G','B']] = label_map[['R','G','B']].astype('int64')

        return colorTableNode

    def runZoneDetection(self, parc, fids, colorLut, lutIdx):
        print(f'Parcellation file: {parc}')
        print(f'Fiducial file: {fids}')
        print(f'LUT list: {colorLut}')
        print(f'LUT id: {lutIdx}')
        # Convert volume to label map
        label_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
        label_node.SetName('aparc+seg')
        volumes_logic = slicer.modules.volumes.logic()
        volumes_logic.CreateLabelVolumeFromVolume(slicer.mrmlScene, label_node, parc)
        # Convert label map to segmentation
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        
        colorTableNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLColorTableNode")
        colorTableNode.SetTypeToUser()
        colorTableNode.HideFromEditorsOff()  # make the color table selectable in the GUI outside Colors module
        print('1')
        slicer.mrmlScene.AddNode(colorTableNode); colorTableNode.UnRegister(None)
        print('2')
        colorTableNode.SetNumberOfColors(14175+1) # Hard coded. Needs to be updated
        print('3')
        colorTableNode.SetNamesInitialised(True) # prevent automatic color name generation
        print('4')
        colorTableNode = self.set_colors(colorTableNode, colorLut[lutIdx-1])
        print('5')
        label_node.GetDisplayNode().SetAndObserveColorNodeID(colorTableNode.GetID())
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(label_node, seg)
        seg.CreateClosedSurfaceRepresentation()
        # Delete previous volume
        slicer.mrmlScene.RemoveNode(parc)
        slicer.mrmlScene.RemoveNode(label_node)
    #     # initialize variables that will hold the number of fiducials 14175
    #     nFids = fids.GetNumberOfFiducials()
    #     # the volumetric atlas
    #     atlas = slicer.util.array(inputAtlas.GetName())
    #     # an the transformation matrix from RAS coordinte to Voxels
    #     ras2vox_atlas = vtk.vtkMatrix4x4()
    #     inputAtlas.GetRASToIJKMatrix(ras2vox_atlas)

    #     # read freesurfer color LUT. It could possibly
    #     # already exists within 3DSlicer modules
    #     # but in python was too easy to read if from scratch that I simply
    #     # read it again.
    #     # FSLUT will hold for each brain area its tag and name
    #     FSLUT = {}
    #     with open(colorLut[lutIdx], 'r') as f:
    #         for line in f:
    #             if not re.match('^#', line) and len(line) > 10:
    #                 lineTok = re.split('\s+', line)
    #                 FSLUT[int(lineTok[0])] = lineTok[1]

    #     with open(os.path.join(os.path.dirname(__file__), './Resources/parc_fullnames.json')) as dataParcNames:
    #         parcNames = json.load(dataParcNames)

    #     with open(os.path.join(os.path.dirname(__file__), './Resources/parc_shortnames.json')) as dataParcAcronyms:
    #         parcAcronyms = json.load(dataParcAcronyms)

    #     # Initialize the progress bar pb
    #     self.pb.setRange(0, nFids)
    #     self.pb.show()
    #     self.pb.setValue(0)

    #     # Update the app process events, i.e. show the progress of the
    #     # progress bar
    #     slicer.app.processEvents()

    #     listParcNames = [x for v in parcNames.values() for x in v]
    #     listParcAcron = [x for v in parcAcronyms.values() for x in v]

    #     for i in xrange(nFids):
    #         # update progress bar
    #         self.pb.setValue(i + 1)
    #         slicer.app.processEvents()

    #         # Only for Active Fiducial points the GMPI is computed
    #         if fids.GetNthFiducialSelected(i) == True:

    #             # instantiate the variable which holds the point
    #             currContactCentroid = [0, 0, 0]

    #             # copy current position from FiducialList
    #             fids.GetNthFiducialPosition(i, currContactCentroid)

    #             # append 1 at the end of array before applying transform
    #             currContactCentroid.append(1)

    #             # transform from RAS to IJK
    #             voxIdx = ras2vox_atlas.MultiplyFloatPoint(currContactCentroid)
    #             voxIdx = numpy.round(numpy.array(voxIdx[:3])).astype(int)

    #             # build a -sideLength/2:sideLength/2 linear mask
    #             mask = numpy.arange(int(-numpy.floor(sideLength / 2)), int(numpy.floor(sideLength / 2) + 1))

    #             # get Patch Values from loaded Atlas in a sideLenght**3 region around
    #             # contact centroid and extract the frequency for each unique
    #             # patch Value present in the region

    #             [X, Y, Z] = numpy.meshgrid(mask, mask, mask)
    #             maskVol = numpy.sqrt(X ** 2 + Y ** 2 + Z ** 2) <= numpy.floor(sideLength / 2)

    #             X = X[maskVol] + voxIdx[0]
    #             Y = Y[maskVol] + voxIdx[1]
    #             Z = Z[maskVol] + voxIdx[2]

    #             patchValues = atlas[Z, Y, X]

    #             # Find the unique values on the matrix above
    #             uniqueValues = numpy.unique(patchValues)

    #             # Flatten the patch value and create a tuple
    #             patchValues = tuple(patchValues.flatten(1))

    #             voxWhite = patchValues.count(2) + patchValues.count(41)
    #             voxGray = len(patchValues) - voxWhite
    #             PTD = float(voxGray - voxWhite) / (voxGray + voxWhite)

    #             # Create an array of frequency for each unique value
    #             itemfreq = [patchValues.count(x) for x in uniqueValues]

    #             # Compute the max frequency
    #             totPercentage = numpy.sum(itemfreq)

    #             # Recover the real patch names
    #             patchNames = [re.sub('((ctx_.h_)|(Right|Left)-(Cerebral-)?)', '', FSLUT[pValues]) for pValues in uniqueValues]
    #             patchAcron = list()
    #             for currPatchName in patchNames:
    #                 currPatchAcron = ''
    #                 for name, acron in zip(listParcNames, listParcAcron):
    #                     if currPatchName == name:
    #                         currPatchAcron = acron

    #                 if currPatchAcron:
    #                     patchAcron.append(currPatchAcron)
    #                 else:
    #                     patchAcron.append(currPatchName)

    #             # Create the zones
    #             parcels = dict(zip(itemfreq, patchAcron))

    #             # prepare parcellation string with percentage of values
    #             # within the ROI centered in currContactCentroid
    #             # [round( float(k) / totPercentage * 100 ) for k,v in parcels.iteritems()]
    #             ordParcels = collections.OrderedDict(sorted(parcels.items(), reverse=True))
    #             anatomicalPositionsString = [','.join([v, str(round(float(k) / totPercentage * 100))]) for k, v in
    #                                          ordParcels.iteritems()]
    #             anatomicalPositionsString.append('PTD, {:.2f}'.format(PTD))

    #             # Preserve if some old description was already there
    #             fids.SetNthMarkupDescription(i, fids.GetNthMarkupDescription(i) + " " + ','.join(
    #                 anatomicalPositionsString))