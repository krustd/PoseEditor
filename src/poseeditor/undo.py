"""姿态编辑用的撤销/重做命令栈。"""

from PySide6.QtCore import QObject, Signal

from .models import Keypoint, PoseData


class UndoCommand:
    """撤销命令抽象基类。"""

    def undo(self):
        pass

    def redo(self):
        pass


class KeypointChangeCommand(UndoCommand):
    def __init__(
        self,
        pose_data: PoseData,
        keypoint_index: int,
        old_state: Keypoint,
        new_state: Keypoint,
    ):
        self.pose_data = pose_data
        self.keypoint_index = keypoint_index
        self.old_state = old_state
        self.new_state = new_state

    def _update_keypoint(self, state: Keypoint):
        current_kp = self.pose_data.keypoints[self.keypoint_index]
        current_kp.x = state.x
        current_kp.y = state.y
        current_kp.visibility = state.visibility

    def undo(self):
        self._update_keypoint(self.old_state)

    def redo(self):
        self._update_keypoint(self.new_state)


class UndoStack(QObject):
    """轻量撤销栈：新命令入栈时会清空重做栈。"""

    can_undo_changed = Signal(bool)
    can_redo_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.undo_stack = []
        self.redo_stack = []

    def push(self, command: UndoCommand):
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.can_undo_changed.emit(True)
        self.can_redo_changed.emit(False)

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        self.can_undo_changed.emit(bool(self.undo_stack))
        self.can_redo_changed.emit(True)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        command = self.redo_stack.pop()
        command.redo()
        self.undo_stack.append(command)
        self.can_undo_changed.emit(True)
        self.can_redo_changed.emit(bool(self.redo_stack))
        return True

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.can_undo_changed.emit(False)
        self.can_redo_changed.emit(False)
