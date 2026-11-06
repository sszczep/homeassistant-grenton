# Tests

The integration folder is `homeassistant_grenton`, but its domain is `grenton`,
so tests run against a `custom_components/grenton` symlink:

```bash
pip install pytest-homeassistant-custom-component PyTurboJPEG
mkdir -p /tmp/grenton-test/custom_components
ln -sfn "$PWD/custom_components/homeassistant_grenton" /tmp/grenton-test/custom_components/grenton
touch /tmp/grenton-test/custom_components/__init__.py
cp -r tests pytest.ini /tmp/grenton-test/
cd /tmp/grenton-test && python -m pytest -q tests
```
