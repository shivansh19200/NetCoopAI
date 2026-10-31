.PHONY: test demo

test:
	python -m pytest -q

demo:
	python -m netcoop.data_generator --output data/sample_telemetry.json
	python -m streamlit run app.py
