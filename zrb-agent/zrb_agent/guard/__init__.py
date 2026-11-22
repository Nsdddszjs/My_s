"""守卫层：伦理与可行性红牌判断。"""

from zrb_agent.guard.ethics import DEVICE_REGION, check_ethics
from zrb_agent.guard.feasibility import Environment, check_feasibility, primary_reason
__all__ = ["DEVICE_REGION", "Environment", "check_ethics", "check_feasibility", "primary_reason"]
