import sys
from pathlib import Path

# Them thu muc src vao python path de import duoc agent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.server.app import app
