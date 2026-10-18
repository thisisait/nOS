"""Code copied into Iris (pupil + face) keeps its upstream MIT notice whole.

MIT allows reuse only if the permission notice ships in full; a header cut after
"EXPRESS OR IMPLIED." drops the liability limitation (layout.ts, 8984916a).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPIED = [ROOT / "files/anatomy/face/src/lib/iris/sequence/layout.ts"]

MIT_TAIL = (
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, '
    "INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR "
    "PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE "
    "FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR "
    "OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER "
    "DEALINGS IN THE SOFTWARE."
)


def _comment_text(path: Path) -> str:
    lines = [l[2:] for l in path.read_text().splitlines() if l.startswith("//")]
    return re.sub(r"\s+", " ", " ".join(lines))


def test_copied_code_carries_the_whole_mit_notice():
    for path in COPIED:
        text = _comment_text(path)
        assert "Permission is hereby granted" in text, path
        assert MIT_TAIL in text, f"{path}: MIT notice is cut short"
