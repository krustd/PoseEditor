from poseeditor.models import PoseData
from poseeditor.undo import KeypointChangeCommand, UndoStack


def test_pose_data_roundtrip_coco_format() -> None:
    pose = PoseData()
    pose.raw_id = 7
    pose.raw_scores = [0.5] * len(pose.keypoints)
    pose.novelty = 3
    pose.environment_interaction = 2
    pose.person_fit = 4
    pose.skip_reason = ""
    pose.keypoints[0].x = 10.0
    pose.keypoints[0].y = 20.0
    pose.keypoints[0].visibility = 1

    loaded = PoseData.from_dict(pose.to_dict())

    assert loaded.raw_id == 7
    assert loaded.keypoints[0].x == 10.0
    assert loaded.keypoints[0].y == 20.0
    assert loaded.keypoints[0].visibility == 1
    assert loaded.novelty == 3
    assert loaded.environment_interaction == 2
    assert loaded.person_fit == 4


def test_pose_data_old_format_compatibility() -> None:
    old_payload = {
        "keypoints": [
            {"name": "nose", "x": 12.5, "y": 8.2, "visibility": 1},
            {"name": "left_eye", "x": 0.0, "y": 0.0, "visibility": 0},
        ]
    }

    loaded = PoseData.from_dict(old_payload)

    assert loaded.keypoints[0].name == "nose"
    assert loaded.keypoints[0].x == 12.5
    assert loaded.keypoints[0].visibility == 1


def test_undo_stack_for_keypoint_change() -> None:
    pose = PoseData()
    kp = pose.keypoints[0]
    old_state = kp.copy()

    kp.x = 30.0
    kp.y = 40.0
    kp.visibility = 1
    new_state = kp.copy()

    stack = UndoStack()
    stack.push(KeypointChangeCommand(pose, 0, old_state, new_state))

    assert stack.undo() is True
    assert pose.keypoints[0].x == old_state.x
    assert pose.keypoints[0].y == old_state.y
    assert pose.keypoints[0].visibility == old_state.visibility

    assert stack.redo() is True
    assert pose.keypoints[0].x == new_state.x
    assert pose.keypoints[0].y == new_state.y
    assert pose.keypoints[0].visibility == new_state.visibility
