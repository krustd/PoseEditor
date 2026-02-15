"""应用级常量定义。"""

DIR_ORIGIN = "images"  # 原图
DIR_JSON = "annotations"  # 标注JSON
DIR_INPAINT = "inpainting"  # inpainting参考图
META_FILE = "meta.json"  # 项目元数据
APP_VERSION = "4.0.0"

# 主图扫描支持的扩展名。
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")

# 补绘参考图支持的扩展名。
INPAINT_EXTENSIONS = IMAGE_EXTENSIONS + (".webp",)

# 界面里展示并绑定快捷键的预设忽略类别。
IGNORE_CATEGORIES = ("美感不足", "难以补全", "背景失真", "比例失调", "图像模糊")
