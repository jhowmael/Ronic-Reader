import sys
from pathlib import Path

# permite `from make_sample_pdf import build` nos testes
sys.path.insert(0, str(Path(__file__).parent))
