import maya.cmds as cmds
from ywta.deform.blendshape import (
    find_replace_target_names,
    find_replace_target_names_regex,
    get_target_list,
)


class BlendshapeTargetRenamerUI:
    """BlendShape Target Renamer UI Class"""

    def __init__(self):
        self.window_name = "blendshapeTargetRenamerUI"
        self.window_title = "BlendShape Target Renamer"
        self.window_size = (400, 300)

        # UI elements
        self.blendshape_field = None
        self.find_field = None
        self.replace_field = None
        self.case_sensitive_checkbox = None
        self.regex_checkbox = None
        self.target_list = None
        self.result_text = None

    def create_ui(self):
        """Create the UI window"""
        # Delete existing window if it exists
        if cmds.window(self.window_name, exists=True):
            cmds.deleteUI(self.window_name)

        # Create main window
        self.window = cmds.window(
            self.window_name,
            title=self.window_title,
            widthHeight=self.window_size,
            sizeable=True,
            resizeToFitChildren=True,
        )

        # Main layout
        main_layout = cmds.columnLayout(
            adjustableColumn=True, rowSpacing=5, columnOffset=("both", 10)
        )

        # Title
        cmds.text(label="BlendShape Target Renamer", font="boldLabelFont", height=30)

        cmds.separator(height=10)

        # BlendShape selection section
        cmds.frameLayout(
            label="BlendShape Selection",
            collapsable=False,
            marginHeight=5,
            marginWidth=5,
        )

        blendshape_layout = cmds.rowLayout(
            numberOfColumns=3,
            columnWidth3=(100, 200, 80),
            columnAlign3=("right", "left", "center"),
            columnAttach3=("right", "both", "left"),
        )

        cmds.text(label="BlendShape:")
        self.blendshape_field = cmds.textField(
            placeholderText="Select or enter blendshape node name"
        )
        cmds.button(label="Get Selected", command=self.get_selected_blendshape)

        cmds.setParent(main_layout)

        # Find & Replace section
        cmds.frameLayout(
            label="Find & Replace", collapsable=False, marginHeight=5, marginWidth=5
        )

        # Find text
        find_layout = cmds.rowLayout(
            numberOfColumns=2,
            columnWidth2=(80, 300),
            columnAlign2=("right", "left"),
            columnAttach2=("right", "both"),
        )
        cmds.text(label="Find:")
        self.find_field = cmds.textField(placeholderText="Text to find")
        cmds.setParent("..")

        # Replace text
        replace_layout = cmds.rowLayout(
            numberOfColumns=2,
            columnWidth2=(80, 300),
            columnAlign2=("right", "left"),
            columnAttach2=("right", "both"),
        )
        cmds.text(label="Replace:")
        self.replace_field = cmds.textField(placeholderText="Text to replace with")
        cmds.setParent("..")

        # Options
        options_layout = cmds.rowLayout(
            numberOfColumns=2, columnWidth2=(150, 150), columnAlign2=("left", "left")
        )
        self.case_sensitive_checkbox = cmds.checkBox(label="Case Sensitive", value=True)
        self.regex_checkbox = cmds.checkBox(label="Use Regex", value=False)
        cmds.setParent("..")

        cmds.setParent(main_layout)

        # Buttons section
        button_layout = cmds.rowLayout(
            numberOfColumns=3,
            columnWidth3=(120, 120, 120),
            columnAlign3=("center", "center", "center"),
            columnAttach3=("both", "both", "both"),
        )

        cmds.button(
            label="Preview",
            command=self.preview_rename,
            backgroundColor=(0.6, 0.8, 1.0),
        )
        cmds.button(
            label="Apply", command=self.apply_rename, backgroundColor=(0.8, 1.0, 0.6)
        )
        cmds.button(label="Refresh Targets", command=self.refresh_target_list)

        cmds.setParent(main_layout)

        # Target list section
        cmds.frameLayout(
            label="Current Targets",
            collapsable=True,
            collapse=False,
            marginHeight=5,
            marginWidth=5,
        )

        self.target_list = cmds.textScrollList(height=100, allowMultiSelection=False)

        cmds.setParent(main_layout)

        # Result section
        cmds.frameLayout(
            label="Results",
            collapsable=True,
            collapse=False,
            marginHeight=5,
            marginWidth=5,
        )

        self.result_text = cmds.scrollField(
            height=80, editable=False, wordWrap=True, text="Ready to rename targets..."
        )

        # Show window
        cmds.showWindow(self.window)

        # Initial refresh
        self.refresh_target_list()

    def get_selected_blendshape(self, *args):
        """Get selected blendshape node from Maya selection"""
        selection = cmds.ls(selection=True)
        if not selection:
            self.show_result("No objects selected.", error=True)
            return

        # Check if selected object is a blendshape node
        for obj in selection:
            if cmds.nodeType(obj) == "blendShape":
                cmds.textField(self.blendshape_field, edit=True, text=obj)
                self.refresh_target_list()
                self.show_result(f"BlendShape node '{obj}' loaded.")
                return

        # Check if selected object has a blendshape in its history
        from ywta.deform.blendshape import get_blendshape_node

        for obj in selection:
            blendshape = get_blendshape_node(obj)
            if blendshape:
                cmds.textField(self.blendshape_field, edit=True, text=blendshape)
                self.refresh_target_list()
                self.show_result(
                    f"BlendShape node '{blendshape}' found from selected geometry."
                )
                return

        self.show_result("No blendshape node found in selection.", error=True)

    def refresh_target_list(self, *args):
        """Refresh the target list"""
        blendshape = cmds.textField(self.blendshape_field, query=True, text=True)

        if not blendshape:
            cmds.textScrollList(self.target_list, edit=True, removeAll=True)
            return

        if not cmds.objExists(blendshape):
            cmds.textScrollList(self.target_list, edit=True, removeAll=True)
            self.show_result(
                f"BlendShape node '{blendshape}' does not exist.", error=True
            )
            return

        if cmds.nodeType(blendshape) != "blendShape":
            cmds.textScrollList(self.target_list, edit=True, removeAll=True)
            self.show_result(f"'{blendshape}' is not a blendShape node.", error=True)
            return

        try:
            targets = get_target_list(blendshape)
            cmds.textScrollList(self.target_list, edit=True, removeAll=True)

            if targets:
                for target in targets:
                    if target:  # Skip None targets
                        cmds.textScrollList(self.target_list, edit=True, append=target)
                self.show_result(f"Found {len([t for t in targets if t])} targets.")
            else:
                self.show_result("No targets found in blendshape.")

        except Exception as e:
            self.show_result(f"Error getting targets: {str(e)}", error=True)

    def preview_rename(self, *args):
        """Preview the rename operation without applying changes"""
        blendshape = cmds.textField(self.blendshape_field, query=True, text=True)
        find_text = cmds.textField(self.find_field, query=True, text=True)
        replace_text = cmds.textField(self.replace_field, query=True, text=True)

        if not self.validate_inputs(blendshape, find_text):
            return

        try:
            # Get current targets
            targets = get_target_list(blendshape)
            if not targets:
                self.show_result("No targets to rename.", error=True)
                return

            # Simulate rename operation
            use_regex = cmds.checkBox(self.regex_checkbox, query=True, value=True)
            case_sensitive = cmds.checkBox(
                self.case_sensitive_checkbox, query=True, value=True
            )

            preview_results = []

            for target in targets:
                if target is None:
                    continue

                if use_regex:
                    import re

                    try:
                        regex = re.compile(find_text)
                        new_name = regex.sub(replace_text, target)
                    except re.error as e:
                        self.show_result(f"Invalid regex pattern: {str(e)}", error=True)
                        return
                else:
                    if case_sensitive:
                        if find_text in target:
                            new_name = target.replace(find_text, replace_text)
                        else:
                            continue
                    else:
                        if find_text.lower() in target.lower():
                            import re

                            new_name = re.sub(
                                re.escape(find_text),
                                replace_text,
                                target,
                                flags=re.IGNORECASE,
                            )
                        else:
                            continue

                if new_name != target:
                    preview_results.append(f"{target} -> {new_name}")

            if preview_results:
                result_text = "Preview Results:\n" + "\n".join(preview_results)
                self.show_result(result_text)
            else:
                self.show_result("No targets would be renamed with current settings.")

        except Exception as e:
            self.show_result(f"Preview error: {str(e)}", error=True)

    def apply_rename(self, *args):
        """Apply the rename operation"""
        blendshape = cmds.textField(self.blendshape_field, query=True, text=True)
        find_text = cmds.textField(self.find_field, query=True, text=True)
        replace_text = cmds.textField(self.replace_field, query=True, text=True)

        if not self.validate_inputs(blendshape, find_text):
            return

        try:
            use_regex = cmds.checkBox(self.regex_checkbox, query=True, value=True)
            case_sensitive = cmds.checkBox(
                self.case_sensitive_checkbox, query=True, value=True
            )

            if use_regex:
                renamed_targets = find_replace_target_names_regex(
                    blendshape, find_text, replace_text
                )
            else:
                renamed_targets = find_replace_target_names(
                    blendshape, find_text, replace_text, case_sensitive
                )

            if renamed_targets:
                result_lines = [f"Successfully renamed {len(renamed_targets)} targets:"]
                for old_name, new_name in renamed_targets.items():
                    result_lines.append(f"  {old_name} -> {new_name}")

                self.show_result("\n".join(result_lines))
                self.refresh_target_list()  # Refresh the target list
            else:
                self.show_result("No targets were renamed.")

        except Exception as e:
            self.show_result(f"Rename error: {str(e)}", error=True)

    def validate_inputs(self, blendshape, find_text):
        """Validate user inputs"""
        if not blendshape:
            self.show_result("Please specify a blendshape node.", error=True)
            return False

        if not cmds.objExists(blendshape):
            self.show_result(
                f"BlendShape node '{blendshape}' does not exist.", error=True
            )
            return False

        if cmds.nodeType(blendshape) != "blendShape":
            self.show_result(f"'{blendshape}' is not a blendShape node.", error=True)
            return False

        if not find_text:
            self.show_result("Please enter text to find.", error=True)
            return False

        return True

    def show_result(self, message, error=False):
        """Show result message in the result text field"""
        if error:
            message = f"ERROR: {message}"

        cmds.scrollField(self.result_text, edit=True, text=message)

        # Also print to Maya's script editor
        if error:
            cmds.warning(message)
        else:
            print(message)


def show_blendshape_target_renamer():
    """Show the BlendShape Target Renamer UI"""
    ui = BlendshapeTargetRenamerUI()
    ui.create_ui()


# For testing
if __name__ == "__main__":
    show_blendshape_target_renamer()
