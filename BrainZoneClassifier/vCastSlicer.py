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
# vCastSlicer. Module to connect 3D Slicer with vCastSender application.
#

class vCastSlicer(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "vCastSlicer"
        self.parent.categories = ["Multiviews"]
        self._dir_chosen = "" # Saves path to vCast exe file
        self.parent.dependencies = []
        self.parent.contributors = ["Mauricio Cespedes Tenorio (Western University)"]
        self.parent.helpText = """
        This tool is made to connect vCastSender application with 3D Slicer.
        """
        self.parent.acknowledgementText = """
        This module was originally developed by Mauricio Cespedes Tenorio (Western University) as part
        of the extension Multiviews.
        """ # <a href="https://github.com/mnarizzano/SEEGA">Multiviews</a>

        # Add app icon when application has started up
        if not slicer.app.commandOptions().noMainWindow:
            slicer.app.connect("startupCompleted()", self.modifyWindowUI)

    def modifyWindowUI(self):
        """
        Function to add custom icon to toolbar.
        """
        # Look for ModuleToolBar in the mainWindow
        mainToolBar = slicer.util.findChild(slicer.util.mainWindow(), 'ModuleToolBar')
        # This condition is made to avoid multiple repetitions of the icon
        add_widget = True
        # Look for elements in the toolbar to search for any instances of vCastSender
        for element in mainToolBar.actions():
            if element.text == "vCastSender":
                add_widget = False
        # If the vCastSender icon is not in the toolbar
        if add_widget:
            iconPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons/vCastSlicer.png')    
            moduleIcon = qt.QIcon(iconPath)
            self.StyleAction = mainToolBar.addAction(moduleIcon, "vCastSender")
            self.StyleAction.triggered.connect(self.toggleStyle)
    
    def toggleStyle(self):
        """
        Function to set behavior of custom icon on click.
        """
        # Message box to give instructions related to vCastSender
        msgbox = qt.QMessageBox()
        # Set style of the message box
        msgbox.setStyleSheet("QLabel{min-width: 700px;}")
        msgbox.setWindowTitle("vCastSender will open.")
        msgbox.setInformativeText("After vCastSender is opened, click 'Device List' and choose your ViewSonic device.")
        msgbox.setStandardButtons(qt.QMessageBox.Cancel | qt.QMessageBox.Ok)
        msgbox.setDefaultButton(qt.QMessageBox.Ok)
        ret = msgbox.exec()
        # If Ok Button is pressed and a vCastSender path has been set
        if ret == qt.QMessageBox.Ok and len(self._dir_chosen)>0:
            try:
                import subprocess
                subprocess.Popen(
                self._dir_chosen, shell = True
                )
            except:
                slicer.util.errorDisplay("Failed to open the exe file. Please verify the path.")
        # If button Cancel is pressed
        elif ret == qt.QMessageBox.Cancel: 
            pass
        else:
            slicer.util.errorDisplay("Failed to open the exe file. Please verify the path.")

#
# vCastSlicer Widget
#

class vCastSlicerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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
        self._dir_chosen = "" # Saves path to vCast exe file
        self._tmp_dir = "" # Saves temp path to vCast exe file before clicking on Apply
        # Defines whether the icon is connected to the function from vCastSlicer class or
        # the vCastSlicerWidget class.
        self._IconConnected = False   

    def setup(self):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)
        # Add or connect icon in toolbar
        self.modifyWindowUI()

        self._loadUI()
        self.logic = vCastSlicerLogic()

        # Connections
        self._setupConnections()
    
    def _loadUI(self):
        """
        Load widget from .ui file (created by Qt Designer).
        """
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/vCastSlicer.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        # UI boot configuration of 'Apply' button and the input box. 
        # If there's a valid path set, it's displayed in the input box and the apply button is enabled.
        if (len(self._dir_chosen)>0 and os.path.isfile(self._dir_chosen)) and self._dir_chosen.endswith('vCastSender.exe'):
            self.ui.vCastSenderSelector.setCurrentPath(self._dir_chosen)
            self.ui.applyButton.toolTip = "Set directory"
            self.ui.applyButton.enabled = True
        else:
            self.ui.applyButton.toolTip = "Please select a valid directory for vCastSender.exe"
            self.ui.applyButton.enabled = False
            

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

        # if inputVolume:
        #     self.ui.outputVolumeSelector.baseName = inputVolume.GetName() + " stripped"
        #     self.ui.outputSegmentationSelector.baseName = inputVolume.GetName() + " mask"

        # All the GUI updates are done
        self._updatingGUIFromParameterNode = False

    def onDirectoryChange(self):
        """
        Function to enable/disable 'Apply' button depending on the selected file
        """
        self._tmp_dir = str(self.ui.vCastSenderSelector.currentPath)
        # If the selected file is a valid one, the button is enabled.
        if (len(self._tmp_dir)>0 and os.path.isfile(self._tmp_dir)) and self._tmp_dir.endswith('vCastSender.exe'):
            self.ui.applyButton.toolTip = "Set directory"
            self.ui.applyButton.enabled = True
        # Else, it is disabled.
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

    def onApplyButton(self):
        """
        Configures the behavior of 'Apply' button by connecting it to the logic function.
        """
        # Path to this script
        pythonScriptPath = os.path.dirname(slicer.util.modulePath(self.moduleName))+'/vCastSlicer.py'
        # Update directory to vCastSender exe file.
        self._dir_chosen = self._tmp_dir
        vCastSlicerLogic().runZoneDetection(str(self.ui.vCastSenderSelector.currentPath), pythonScriptPath)
    
    # Function to add icon
    def modifyWindowUI(self):
        # Look for ModuleToolBar in the mainWindow
        mainToolBar = slicer.util.findChild(slicer.util.mainWindow(), 'ModuleToolBar')
        # Variable that saved id of vCast Icon if found
        vCastIconIdx = None
        for idx,element in enumerate(mainToolBar.actions()):
            if element.text == "vCastSender":
                vCastIconIdx = idx
        # If vCast Icon was not found, it's added to the toolbar
        if vCastIconIdx ==  None:        
            moduleIcon = qt.QIcon(self.resourcePath('Icons/vCastSlicer.png'))
            self.StyleAction = mainToolBar.addAction(moduleIcon, "vCastSender")
            self.StyleAction.triggered.connect(self.toggleStyle)
        # Reset connection (as it was started with the connection from vCastSlicer class)
        elif self._IconConnected == False:
            self._IconConnected = True
            mainToolBar.actions()[idx].triggered.disconnect()
            mainToolBar.actions()[idx].triggered.connect(self.toggleStyle)

    # Function to set behavior of icon on click
    def toggleStyle(self):
        # Message box to give instructions related to vCastSender
        msgbox = qt.QMessageBox()
        # Set style of the message box
        msgbox.setStyleSheet("QLabel{min-width: 700px;}")
        msgbox.setWindowTitle("vCastSender will open.")
        msgbox.setInformativeText("After vCastSender is opened, click 'Device List' and choose your ViewSonic device.")
        msgbox.setStandardButtons(qt.QMessageBox.Cancel | qt.QMessageBox.Ok)
        msgbox.setDefaultButton(qt.QMessageBox.Ok)
        ret = msgbox.exec()
        # If Ok Button is pressed and a vCastSender path has been set
        if ret == qt.QMessageBox.Ok and len(self._dir_chosen)>0:
            try:
                import subprocess
                subprocess.Popen(
                self._dir_chosen, shell = True
                )
            except:
                slicer.util.errorDisplay("Failed to open the exe file. Please verify the path.")
        # If button Cancel is pressed
        elif ret == qt.QMessageBox.Cancel: 
            pass
        else:
            slicer.util.errorDisplay("Failed to open the exe file. Please verify the path.")

#########################################################################################
####                                                                                 ####
#### vCastSlicerLogic                                                          ####
####                                                                                 ####
#########################################################################################
class vCastSlicerLogic(ScriptedLoadableModuleLogic):
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
        """
        Updates this file by changing the default _dir_chosen attribute from
        the vCastSlicer and vCastSlicerWidget classes so that the next time
        3D Slicer is launched, the directory to vCastSender.exe is saved.
        """
        line_to_replace = r'self._dir_chosen = ".*"'
        replacement = f'self._dir_chosen = "{vCastSenderPath}"'
        self.replacer(pythonScriptPath, line_to_replace, replacement)
    
    def replacer(self, file_path, pattern, subst):
        """
        Method to replace a specific pattern in a file to a substitute text.
        """
        #Create temp file to write updates
        fh, abs_path = mkstemp()
        with fdopen(fh,'w') as new_file:
            with open(file_path) as old_file:
                cond = 0 # Condition to only replace first 2 matches
                i = 0 # id to avoid touching this function
                for line in old_file:
                    # Get new line based on conditions
                    if (cond<2) and (i<280):
                        tmp_line = re.sub(pattern, subst, line)
                        # Update condition
                        if line != tmp_line:
                            cond += 1
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