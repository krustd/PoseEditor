"""关键点与姿态标注的数据模型。"""

from typing import Any, Dict, List, Tuple


class Keypoint:
    """关键点数据模型"""

    def __init__(self, name: str, x: float = 0, y: float = 0, visibility: int = 0):
        self.name = name
        self.x = x
        self.y = y
        self.visibility = visibility  # 0: 遮挡, 1: 可见

    def copy(self) -> "Keypoint":
        return Keypoint(self.name, self.x, self.y, self.visibility)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "visibility": self.visibility,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Keypoint":
        return cls(data["name"], data["x"], data["y"], data["visibility"])


class PoseData:
    """姿态数据模型，支持 COCO 风格 JSON 标注格式。"""

    KEYPOINT_NAMES = [
        "nose",
        "left_eye",
        "right_eye",
        "left_ear",
        "right_ear",
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    ]

    def __init__(self):
        self.keypoints = self._init_keypoints()

        # 保留原始检测数据（模型输出，不可修改）
        self.raw_id = 0
        self.raw_scores = []  # 模型置信度分数

        # 评分字段
        self.novelty = -1  # 姿势新奇度：0到5分
        self.environment_interaction = -1  # 环境互动性：0到5分
        self.person_fit = -1  # 人物契合度：0到5分

        # 跳过原因
        self.skip_reason = ""  # 空字符串表示不跳过，否则记录跳过原因

        # 兼容旧格式
        self.score = -1

    def copy(self) -> "PoseData":
        new_pose = PoseData()
        new_pose.keypoints = [kp.copy() for kp in self.keypoints]
        new_pose.raw_id = self.raw_id
        new_pose.raw_scores = self.raw_scores.copy()
        new_pose.score = self.score
        new_pose.novelty = self.novelty
        new_pose.environment_interaction = self.environment_interaction
        new_pose.person_fit = self.person_fit
        new_pose.skip_reason = self.skip_reason
        return new_pose

    def _init_keypoints(self) -> List[Keypoint]:
        return [Keypoint(name) for name in self.KEYPOINT_NAMES]

    def to_dict(self) -> Dict[str, Any]:
        """输出为 COCO 风格 JSON 格式。"""
        return {
            "id": self.raw_id,
            "keypoints": [[kp.x, kp.y] for kp in self.keypoints],
            "scores": self.raw_scores
            if self.raw_scores
            else [0.0] * len(self.keypoints),
            "visibility": [kp.visibility for kp in self.keypoints],
            "novelty": self.novelty,
            "environment_interaction": self.environment_interaction,
            "person_fit": self.person_fit,
            "skip_reason": self.skip_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PoseData":
        """从标注数据加载（兼容 COCO 风格 JSON 与旧格式）。"""
        pose = cls()

        # 读取评分字段
        pose.novelty = data.get("novelty", -1)
        pose.environment_interaction = data.get(
            "environment_interaction", data.get("environment_fit", -1)
        )
        pose.person_fit = data.get("person_fit", -1)
        pose.skip_reason = data.get("skip_reason", "")
        pose.score = data.get("score", -1)

        raw_kps = data.get("keypoints", [])

        # 判断格式：COCO 风格二维坐标数组，或旧版字段字典列表。
        if raw_kps and isinstance(raw_kps[0], list):
            # ---- COCO 风格 JSON ----
            pose.raw_id = data.get("id", 0)
            pose.raw_scores = data.get("scores", [])
            visibility_list = data.get("visibility", [])

            for i, kp in enumerate(pose.keypoints):
                if i < len(raw_kps):
                    kp.x = raw_kps[i][0]
                    kp.y = raw_kps[i][1]
                # 可见性优先使用显式标注，否则根据分数阈值初始化。
                if i < len(visibility_list):
                    kp.visibility = visibility_list[i]
                elif i < len(pose.raw_scores) and pose.raw_scores[i] > 0.3:
                    kp.visibility = 1  # 置信度高则默认可见

        elif raw_kps and isinstance(raw_kps[0], dict):
            # ---- 旧的自定义格式（向后兼容）----
            for i, kp_data in enumerate(raw_kps):
                if i < len(pose.keypoints):
                    pose.keypoints[i] = Keypoint.from_dict(kp_data)

        return pose

    def has_valid_keypoints(self) -> bool:
        """检查是否有有效的关键点坐标（不全为0）"""
        for kp in self.keypoints:
            if kp.x > 1 and kp.y > 1:  # 简单的阈值判断
                return True
        return False

    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """获取有效关键点包围盒，返回最小与最大坐标。"""
        valid_points = [(kp.x, kp.y) for kp in self.keypoints if kp.x > 1 and kp.y > 1]
        xs = [x for x, _ in valid_points]
        ys = [y for _, y in valid_points]

        if not xs or not ys:
            return (0, 0, 0, 0)

        return (min(xs), min(ys), max(xs), max(ys))
