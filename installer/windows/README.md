# Windows installer

This directory contains the first Windows-only installer for CommaMatrix.

The release installer is started with the PowerShell script published as a
GitHub release asset. It installs `uv` globally with the official uv installer,
uses uv-managed Python 3.13, creates the application environment in
`%USERPROFILE%\\commamatrix`, and installs `commamatrix[all]` together with the
desktop runtime dependencies.

Before publishing a release, populate `providers.json` with the supported
providers. The file intentionally does not contain a model list. Each provider
may define one `recommended_model`; Advanced mode lets the user replace it.

The installer version is the CommaMatrix release version. `manifest.json`
checks that the wheel and installer resources belong to the same Git tag before
installation starts.
