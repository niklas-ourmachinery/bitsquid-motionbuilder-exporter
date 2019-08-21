# Exports snapshotted data from a motion builder scene into BitSquid's
# internal data format. Each take in the scene is exported to a separate
# file in a directory selected by the user.

from pyfbsdk import FBSystem, FBApplication ,  FBFbxOptions, FBLabel, ShowTool, FBAddRegionParam, FBAttachType, FBImageContainer, FBList, FBFileFormatAndVersion, FBButton, FBButtonStyle, FBTextJustify, FBFolderPopup, FBFilePopup, FBFilePopupStyle, FBPlayerControl, FBTime, FBMatrix, FBModelTransformationMatrix, FBProgress

from pyfbsdk_additions import ToolList, DestroyToolByName, CreateUniqueTool, HBoxLayout

import re, os, os.path, sys, _winreg

# Global objects and settings
TOOL_NAME = "BitSquid Exporter"
SYSTEM = FBSystem()
APP = FBApplication()
SCENE = FBSystem().Scene

# Class that handles updating the motion builder progress bar based on current take and frame
# number. Typical usage:
#
#	progress.begin()				# starts displaying the progress bar
#	progress.takes = 10				# sets the number of takes to export
#	for t in takes:
#		progress.frames = 100		# sets the number of frames in the current take
#		for f in frames:
#			# export
#			progress.next_frame()	# tells the progress bar that one frame has been processed
#		progress.next_take()		# tells the progerss bar that one take has been processed
class Progress:
	def __init__(self):
		self.progress = FBProgress()
		self.progress.Caption = "Exporting"
		self.takes = 1
		self.take = 0
		self.frames = 1
		self.frame = 0
	def begin(self):
		self.progress.ProgressBegin()
	def end(self):
		self.progress.ProgressDone()
	def set_text(self,text):
		self.progress.Text = text
	def next_take(self):
		self.take = self.take + 1
		self.frame = 0
	def next_frame(self):
		self.frame = self.frame + 1
		self.update_progress()
	def update_progress(self):
		progress = self.take / float(self.takes) + self.frame / float(self.frames) / float(self.takes)
		self.progress.Percent = int(progress*100)

# Global progress bar object
PROGRESS = Progress()

# Implement FBMatrix multiplication, because strangely it isn't defined in
# the autodesk SDK.
def multiply(A, B):
	Aa,Ab,Ac,Ad,Ae,Af,Ag,Ah,Ai,Aj,Ak,Al,Am,An,Ao,Ap = A[0],A[1],A[2],A[3],A[4],A[5],A[6],A[7],A[8],A[9],A[10],A[11],A[12],A[13],A[14],A[15]
	Ba,Bb,Bc,Bd,Be,Bf,Bg,Bh,Bi,Bj,Bk,Bl,Bm,Bn,Bo,Bp = B[0],B[1],B[2],B[3],B[4],B[5],B[6],B[7],B[8],B[9],B[10],B[11],B[12],B[13],B[14],B[15]
	
	C = FBMatrix()
	C[0] = Aa * Ba + Ab * Be + Ac * Bi + Ad * Bm
	C[1] = Aa * Bb + Ab * Bf + Ac * Bj + Ad * Bn
	C[2] = Aa * Bc + Ab * Bg + Ac * Bk + Ad * Bo
	C[3] = Aa * Bd + Ab * Bh + Ac * Bl + Ad * Bp
	C[4] = Ae * Ba + Af * Be + Ag * Bi + Ah * Bm
	C[5] = Ae * Bb + Af * Bf + Ag * Bj + Ah * Bn
	C[6] = Ae * Bc + Af * Bg + Ag * Bk + Ah * Bo
	C[7] = Ae * Bd + Af * Bh + Ag * Bl + Ah * Bp
	C[8] = Ai * Ba + Aj * Be + Ak * Bi + Al * Bm
	C[9] = Ai * Bb + Aj * Bf + Ak * Bj + Al * Bn
	C[10] = Ai * Bc + Aj * Bg + Ak * Bk + Al * Bo
	C[11] = Ai * Bd + Aj * Bh + Ak * Bl + Al * Bp
	C[12] = Am * Ba + An * Be + Ao * Bi + Ap * Bm
	C[13] = Am * Bb + An * Bf + Ao * Bj + Ap * Bn
	C[14] = Am * Bc + An * Bg + Ao * Bk + Ap * Bo
	C[15] = Am * Bd + An * Bh + Ao * Bl + Ap * Bp
	return C

# Gets the current local transform of the node as an FBMatrix
def get_node_transform(node):
	node_tm = FBMatrix()
	node.GetMatrix(node_tm)
	if not node.Parent:
		rotate = FBMatrix([-1,0,0,0,  0,0,1,0,  0,1,0,0,  0,0,0,1])
		fix = multiply(node_tm, rotate)
		return fix
	parent_inv_tm = FBMatrix()
	node.Parent.GetMatrix(parent_inv_tm, FBModelTransformationMatrix.kModelInverse_Transformation)
	return multiply(node_tm, parent_inv_tm)

# Returns the current transform of all the nodes in the list items as a
# list of FBMatrix
def snapshot(items):
	snapshot = []
	for i in items:
		snapshot.append(get_node_transform(i))
	return snapshot

# Returns the animation for the take. The animation is returned as
# a list of snapshots, one for each frame.
def get_animation(take, items):
	SYSTEM.CurrentTake = take
	SCENE.Evaluate()
	player = FBPlayerControl()
	
	timespan = take.LocalTimeSpan
	scene_start_frame = timespan.GetStart().GetFrame(True)
	scene_end_frame = timespan.GetStop().GetFrame(True)
	frame = scene_start_frame
	player.Goto(FBTime(0, 0, 0, frame))
	
	PROGRESS.frames = scene_end_frame
	
	snapshots = []
	
	while True:
		SCENE.Evaluate()
		snapshots.append(snapshot(items))
		if frame >= scene_end_frame:
			break
		player.StepForward()
		frame = frame + 1
		PROGRESS.next_frame()
	return snapshots

# Returns a linear list (in breadth-first order) of all the children of the
# node root.
def get_all_children(root):
	children = [root]
	work = [root]
	
	while len(work) > 0:
		item = work.pop(0)
		for n in item.Children:
			work.append(n)
			children.append(n)
			
	return children

# Converts the animation to bitsquid exporter format
def write_bsi(f, items, anim):
	def write_times(f, n):
		# Assume 30 FPS frame rate
		fps = 30
		for i in range(n):
			f.write("%f " % (float(i)/fps))
			
	def write_data(f, i, anim):
		# Assume centimeter scale
		scale = 0.01
		for t in range(len(anim)):
			m = anim[t][i]
			f.write("\n                ")
			f.write("%f %f %f %f " % (m[0], m[1], m[2], m[3]))
			f.write("%f %f %f %f " % (m[4], m[5], m[6], m[7]))
			f.write("%f %f %f %f " % (m[8], m[9], m[10], m[11]))
			f.write("  %f %f %f %f " % (m[12]*scale, m[13]*scale, m[14]*scale, m[15]))

	def write_bsi_node(f, name, i, anim):
		f.write("    {\n")
		f.write("        node = \"%s\"\n" % name)
		f.write("        parameter = \"matrix\"\n")
		f.write("        stream = {\n")
		f.write("            channels = [{ index = 0 name = \"local_tm\" type = \"CT_MATRIX4x4\" }] \n")
		f.write("            data = [ "); write_data(f,i,anim); f.write("]\n")
		f.write("            size = %i\n" % len(anim))
		f.write("            stride = 64\n")
		f.write("        }\n")
		f.write("        times = [ "); write_times(f, len(anim)); f.write("]\n")
		f.write("    }\n")

	f.write("animations = [\n")
	for i in range(len(items)):
		write_bsi_node(f, items[i].Name, i, anim)
	f.write("]\n")

# Finds a specific node in the scene
def find_node(name):
	for item in get_all_children(SCENE.RootModel):
		if item.Name == name:
			return item
	return None
	
# Finds a specific take in the scene
def find_take(name):
	for item in SCENE.Takes:
		if item.Name == name:
			return item
	return None
		
# Exports the take to a file in the specified directory
def export_take(dir, take):
	PROGRESS.set_text(take.Name)
	# Find root node by name convention root_point
	root = find_node("root_point")
	items = get_all_children(root)
	anim = get_animation(take, items)
	path = os.path.join(dir, take.Name + ".bsi")
	f = open(path, "w")
	write_bsi(f, items, anim)
	f.close()
	
# Returns true if the take should be exported.
# Returns true if the name consists of alphanumeric uncapitalized letters
# and underscore.
def should_export(take):
	return re.match("^[a-z_0-9]*$", take.Name)
	
# Exports takes as individual files in the specified directory
def export_takes(dir, takes):
	PROGRESS.begin()
	PROGRESS.takes = len(takes)
	for take in takes:
		export_take(dir, take)
		PROGRESS.next_take()
	PROGRESS.end()

# Exports all takes as individual files in the specified directory
def export_all(dir):
	PROGRESS.begin()
	PROGRESS.takes = len(SCENE.Takes)
	for take in SCENE.Takes:
		if should_export(take):
			export_take(dir, take)
		PROGRESS.next_take()
	PROGRESS.end()
	
def get_config_value(key, defval=None):
	try:
		cfg_root_key = _winreg.CreateKey(_winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\BitSquid\\BSIExporter\\")
		return _winreg.QueryValue(cfg_root_key, key)
	except Exception,e:
		return defval

def set_config_value(key, value):
	try:
		cfg_root_key = _winreg.CreateKey(_winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\BitSquid\\BSIExporter\\")
		_winreg.SetValue(cfg_root_key, key, _winreg.REG_SZ, value) 
		cfg_root_key.Close()
	except Exception, e:
		pass
		

TAKE_BUTTONS = []

# Creates the UI for the main dialog box
def build_ui(main):
	global TAKE_BUTTONS
	TAKE_BUTTONS = []
	
	# Callback when the [Export...] button is pressed.
	def export_callback(control, event):
		takes = []
		for button in TAKE_BUTTONS:
			if button.State:
				for t in SCENE.Takes:
					if t.Name == button.Caption:
						takes.append(t)
						
		config = takes[0].Name
		path = get_config_value(config + "\\export_path")
						
		popup = FBFilePopup()
		popup.Caption = "Export takes to"
		popup.Filter = "*.bsi"
		popup.FileName = config + ".bsi";
		if path:
			popup.Path = os.path.dirname(path)
		popup.Style = FBFilePopupStyle.kFBFilePopupSave
		if popup.Execute():
			for t in takes:
				set_config_value(t.Name + "\\export_path", popup.FullFilename)
			dir = os.path.dirname(popup.FullFilename)
			export_takes(dir, takes)
			
	x = FBAddRegionParam(10,FBAttachType.kFBAttachNone,"")
	y = FBAddRegionParam(-40,FBAttachType.kFBAttachBottom,"")
	w = FBAddRegionParam(-100,FBAttachType.kFBAttachRight,"")
	h = FBAddRegionParam(-10,FBAttachType.kFBAttachBottom,"")
	main.AddRegion("label","label", x, y, w, h)
	
	label = FBLabel()
	label.Caption = ("* Root point must be named 'root_point'\n" +
					"* Assumes 30 FPS and cm scale")
	main.SetControl("label",label)
	
	ntakes = 0
	for take in SCENE.Takes:
		if should_export(take):
			ntakes = ntakes + 1
			
	ypos = 10
	xpos = 10
	i = 0
	row = 0
	rows = 25
	if ntakes/3 > rows:
		rows = ntakes/3
	for take in SCENE.Takes:
		if should_export(take):
			x = FBAddRegionParam(xpos,FBAttachType.kFBAttachNone,"")
			y = FBAddRegionParam(ypos,FBAttachType.kFBAttachNone,"")
			w = FBAddRegionParam(200,FBAttachType.kFBAttachNone,"")
			h = FBAddRegionParam(20,FBAttachType.kFBAttachNone,"")
			ypos = ypos + 20
			
			row = row + 1
			if row >= rows:
				ypos = 10
				xpos = xpos + 200
				row = 0
			main.AddRegion("take" + str(i),"take" + str(i), x, y, w, h)
			TAKE_BUTTONS.append(FBButton())
			TAKE_BUTTONS[i].Caption = take.Name
			TAKE_BUTTONS[i].Style = FBButtonStyle.kFBCheckbox
			TAKE_BUTTONS[i].State = 0
			main.SetControl("take" + str(i),TAKE_BUTTONS[i])
			i = i + 1
			
	x = FBAddRegionParam(-72,FBAttachType.kFBAttachRight,"")
	y = FBAddRegionParam(-30,FBAttachType.kFBAttachBottom,"")
	w = FBAddRegionParam(70,FBAttachType.kFBAttachNone,"")
	h = FBAddRegionParam(25,FBAttachType.kFBAttachNone,"")
	main.AddRegion("button","button", x, y, w, h)
	
	export_button = FBButton()
	export_button.Caption = "Export BSI.."
	export_button.Justify = FBTextJustify.kFBTextJustifyCenter
	main.SetControl("button",export_button)
	export_button.OnClick.Add(export_callback)

def rebuild_ui(control, event):
	global TAKE_BUTTONS
	i = 0
	for button in TAKE_BUTTONS:
		control.RemoveRegion("take" + str(i))
		control.ClearControl("take" + str(i))
		i = i + 1
	build_ui(control)
  
# Creates the motion builder tool
def create_tool():		
	t = CreateUniqueTool(TOOL_NAME)
	t.StartSizeX = 600
	t.StartSizeY = 600
	build_ui(t)
	t.OnShow.Add(rebuild_ui)
	return t
 
QUICK_TEST = False
DEVELOPMENT = True

if QUICK_TEST:
	PROGRESS.begin()
	export_take("D:\Work\hamilton\units", find_take("button"))
	PROGRESS.end()
else:
	if DEVELOPMENT:
		DestroyToolByName(TOOL_NAME)

	if TOOL_NAME in ToolList:
		tool = ToolList[TOOL_NAME]
		ShowTool(tool)
	else:
		tool = create_tool()
		if DEVELOPMENT:
		   ShowTool(tool)