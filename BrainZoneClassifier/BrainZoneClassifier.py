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
from tempfile import mkstemp
from shutil import move, copymode
from os import fdopen, remove

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
        self._dir_chosen = "C:/Program Files (x86)/Viewsonic/vCastSender/vCastSender.exe"
        self._tmp_dir = ""
        self._GUI_added = False
        self._Nodes_selected = False
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
        self.logic = BrainZoneClassifierLogic()

        # Connections
        self._setupConnections()
    
    def _loadUI(self):
        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/BrainZoneClassifier.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

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
        self.ui.vCastSenderSelector.connect("currentPathChanged(QString)", self.onDirectoryChange)
        # print('ca')

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

        # if inputParameterNode:
        #     self.logic.setDefaultParameters(inputParameterNode)

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
        # self.ui.vCastSenderSelector.setCurrentNode(self._parameterNode.GetNodeReference("vCastSender"))
        print('aqui')

        # Update buttons states and tooltips
        vCastSender = self._parameterNode.GetNodeReference("vCastSender")
        # Condition to change button: self._bool_plan
        # Set state of apply button
        if vCastSender:
            self.ui.applyButton.toolTip = "Extract positions"
            self.ui.applyButton.enabled = True
        else:
            self.ui.applyButton.toolTip = "Input a path for vCastSender"
            self.ui.applyButton.enabled = False
            self._Nodes_selected = False

        # if inputVolume:
        #     self.ui.outputVolumeSelector.baseName = inputVolume.GetName() + " stripped"
        #     self.ui.outputSegmentationSelector.baseName = inputVolume.GetName() + " mask"

        # All the GUI updates are done
        self._updatingGUIFromParameterNode = False

    def onDirectoryChange(self):
        self._tmp_dir = str(self.ui.vCastSenderSelector.currentPath)
        if (len(self._tmp_dir)>0 and os.path.isfile(self._tmp_dir)) and self._tmp_dir.endswith('vCastSender.exe'):
            self.ui.applyButton.toolTip = "Set directory"
            self.ui.applyButton.enabled = True
        else:
            self.ui.applyButton.toolTip = "Please select a valid directory for vCastSender.exe"
            self.ui.applyButton.enabled = False

    def updateParameterNodeFromGUI(self, caller=None, event=None):
        """
        This method is called when the user makes any change in the GUI.
        The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
        """

        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

        self._parameterNode.SetNodeReferenceID("vCastSender", self.ui.vCastSenderSelector.currentNodeID)

        self._parameterNode.EndModify(wasModified)

    #######################################################################################
    ###  onZoneButton                                                                 #####
    #######################################################################################
    def onApplyButton(self):
        pythonScriptPath = os.path.dirname(slicer.util.modulePath(self.moduleName))+'/BrainZoneClassifier.py'
        # Update directory for widget
        self._dir_chosen = self._tmp_dir
        slicer.util.showStatusMessage("START Zone Detection")
        print ("RUN Zone Detection Algorithm")
        BrainZoneClassifierLogic().runZoneDetection(str(self.ui.vCastSenderSelector.currentPath), pythonScriptPath)
        print ("END Zone Detection Algorithm")
        slicer.util.showStatusMessage("END Zone Detection")
    
    def modifyWindowUI(self):
        mainToolBar = slicer.util.findChild(slicer.util.mainWindow(), 'ModuleToolBar')
        add_widget = True
        for element in mainToolBar.actions():
            if element.text == "vCastSender":
                add_widget = False
        if add_widget:        
            moduleIcon = qt.QIcon(self.resourcePath('Icons/BrainZoneClassifier.png'))
            self.StyleAction = mainToolBar.addAction(moduleIcon, "vCastSender")
            self.StyleAction.triggered.connect(self.toggleStyle)
        
    def toggleStyle(self):
        print('aqui slicer')
        msgbox = qt.QMessageBox()
        # font = qt.QFont()
        # font.setBold(True)
        msgbox.setStyleSheet("QLabel{min-width: 700px;}")
        msgbox.setWindowTitle("vCastSender will open.")
        msgbox.setInformativeText("After vCastSender is opened, click 'Device List' and choose your ViewSonic device.")
        msgbox.setStandardButtons(qt.QMessageBox.Cancel | qt.QMessageBox.Ok)
        msgbox.setDefaultButton(qt.QMessageBox.Ok)
        ret = msgbox.exec()
        if ret == qt.QMessageBox.Ok and len(self._dir_chosen)>0:
            try:
                import subprocess
                subprocess.Popen(
                self._dir_chosen, shell = True
                )
            except:
                slicer.util.errorDisplay("Failed to open the exe file. Please verify the path.")
        else:
            slicer.util.errorDisplay("Failed to open the exe file. Please verify the path.")

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

    def runZoneDetection(self, vCastSenderPath, pythonScriptPath):
        print(f'Path: {vCastSenderPath}')
        line_to_replace = 'self._dir_chosen = ""'
        replacement = f'self._dir_chosen = "{vCastSenderPath}"'
        print(type(vCastSenderPath))
        print(type(replacement))
        print((pythonScriptPath, line_to_replace, replacement))
        self.replacer(pythonScriptPath, line_to_replace, replacement)
    
    def replacer(self, file_path, pattern, subst):
        #Create temp file to write updates
        fh, abs_path = mkstemp()
        with fdopen(fh,'w') as new_file:
            with open(file_path) as old_file:
                cond = True # Condition to only replace first match
                i = 0 # id to avoid touching this function
                for line in old_file:
                    tmp_line = line.replace(pattern, subst)
                    # Get new line based on conditions
                    if cond and (i<280):
                        tmp_line = line.replace(pattern, subst)
                        # Update condition
                        if line != tmp_line:
                            cond = False
                    else:
                        tmp_line = line
                    # Write line
                    new_file.write(tmp_line)
                    i +=1
                    
        #Copy the file permissions from the old file to the new file
        copymode(file_path, abs_path)
        #Remove original file
        remove(file_path)
        #Move new file
        move(abs_path, file_path)