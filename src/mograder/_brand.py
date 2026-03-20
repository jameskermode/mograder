"""Branding constants: favicon link tag and inline logo HTML."""

from __future__ import annotations

from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent


def _read_head_html() -> str:
    return (_PKG_DIR / "head.html").read_text()


FAVICON_LINK = _read_head_html()

_LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAABmJLR0QA/wD/AP+gvaeTAAAFMElE"
    "QVR4nO2bXWwUVRTHf2empexu/UCJLVVQY4QQ+UwMPGiMvhSQSqAF9MEgT1h2tRBioo/7amIiUG"
    "gJMaI8mVIWIlAEE30yRqMhBRKDEQwqljUIEuiUfsw9Puy0lGa27c5umS3s72nux7n3f8+ee2cye"
    "wZKlChR4j5GAlklk1Z08ZVqjDtDDNMKrCkn1OIaxv3bOVOTJpk0udrn5IBY++YFKiSAVUB1rpNN"
    "MF3AEbHtXd2rd50Zr9H4HNAWr4zauhN4C7CC6btrGEQ+cwbYwvqWm2N1HtMBkYPvPiEMHAMWeF"
    "V9wFcIJ0EvisqtPAXnhYpOBXkSpRZYAZR7TZ1KWV1PQ/Nfo9mP7oDML/8dQ4uXDtcaaOpds/d8"
    "3songIpDm56xXbsZYYVX1em48uJokTBqOEdt08ztxe9yzjz2WrEuHqB3zd7zztmqOpTdXtXCqK"
    "0fj2aTNQK8A+8UYKEcd85W1QU5ZUMhmbSi89MdwDLAtUQX3azfc9ava9YIUPQdr73fNdI0aRYPk"
    "EwaA3Ey55VtjCSydfV3QDJpIVLnlY73rm/5rfAqC0fkcHxm5HB85vC6Ww2tF1BOAiCsQv2j3dc"
    "B0cVXqoEZmZKcKKTYQhM51LhEXP1VXD030gmKDmqviR2IV/nZ+0dAf3/NsGEuBhbXnlgaaU8sn"
    "Sj7h45uniZGvgCm4rMWwRrSrrbUjGzHzwjAUqkcujbanYvoO8YRnWuJzp0Qe0X6b/EJ8HSmyAc"
    "9q1v+vMNezY2ha+M+6DtHUHFhE0lt3oJQD4BytKe+dUeQccoKqqoQfJssi/6XXug8XNXJ1X98u0"
    "QONS4Rw4de8ffyqWxA0CDTFV0ERP9Nb8fwU/Ra+phiTRnZPmzfTwH61NI3rte1Xgs6X9E5ANHM7"
    "UqpBdN0hxMU6e/lU27v+/d71uz5MZ/pis4BTqR8G3AsU9LnRNxt7H8vBt6+h9WZpuD7fjhF5wBe"
    "be51ImUNeE5QZU4sdrOj8kDjy8LQvv/DtqyNQff9cPI6BCPtiaWWpXOytYvqCwCxVDy3x+hbLop"
    "1GDWLEB5X5CW19BtAEBlA2WfQlbFUHGPkXM/a3T8EXUPxRYCHiPYJ8jXKpcEaAFVtE+FCoebJK"
    "wI8z2f1fuxg3ALorm/ZH2T8jL39PeI2oNSipHoaWt8sROgPUrQRMIhg+pxpVSuxeN55tOr1Qi4e"
    "ivFByI9XkgMO/DwRQxd9BEw0JQeELSBsSg4IW0DYlBwQtoCwKTkgbAFhU3JA2ALCpjjfB+Rgf8"
    "++D7hbTIL3AcHtx8N9HwElB4QtIGxKDghbQNjc9w7wvQ2aMrmB9+hhxHog6OBG5ZegtgWxt2Qo"
    "J8AI1/36+D8HWHYXxvWudVZQAfk8oRXCXlVnSeb/FMRYXX59fLeAc2r6ZTK5t6Asy0dEmAgyqP"
    "1S97qWtF+fbFliBjjilZZXtL/9bOHlTSwVqcRsZOjH+zLbHypZD0HJZFsaoNwWayfJ5OQ5MNvW2"
    "TammUzesGuJtmTrmnVR3WtbTwOfe8Xl0XnpyeGEtnV21Jq+w0ueBtiXLUsUxrgNOq40AacBEBLR+"
    "emOYt4OFanE7GjZ9A4y3zQAdDrdsa2j2Yw3Xf4osNCr6kc5oegJwboooj156s4LVYmo6FOi1Hp7v"
    "oDp8oNk0ua3AxsBOx/BdwEX2Od0x7ay4aMxcxxz+mSmMtU4zxhJIKwCfDMvQ+QSyhHL0t2j7fmR"
    "BPtoSpFoalM1lM8QzCOBxigQinUV+ruc+r2XC507UKJEiRL3PP8De83XSDlzZrcAAAAASUVORK5C"
    "YII="
)


def logo_html(size: int = 48) -> str:
    """Return an ``<img>`` tag with the mograder logo as an inline data URI."""
    return (
        f'<img src="data:image/png;base64,{_LOGO_B64}"'
        f' width="{size}" height="{size}" alt="mograder"'
        f' style="vertical-align: middle;">'
    )
