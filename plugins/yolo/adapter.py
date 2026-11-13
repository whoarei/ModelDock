from modeldock_sdk.vision import OnnxVision


class Plugin(OnnxVision):
    """YOLOv8, [1, 4+C, N], xywh in 640px input, no embedded NMS."""
