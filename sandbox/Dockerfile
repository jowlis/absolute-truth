# The image the agents' Python code runs in (see tools/sandbox.py).
# Built once, automatically, by run.py. Network is used only while building;
# the code itself always runs with no network, no files and no secrets.
FROM python:3.13-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath
