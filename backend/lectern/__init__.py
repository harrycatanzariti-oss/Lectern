"""Lectern: turns lecture slides and textbooks into a course that teaches you."""
from pathlib import Path

from dotenv import load_dotenv

# Before any module reads its settings from the environment.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
