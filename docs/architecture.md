# Architecture

The frontend calls the FastAPI service. The detection service chooses YOLO11 segmentation when weights exist and an OpenCV fallback otherwise. Detection measurements flow into the severity service, then are persisted as an inspection plus damage rows in PostgreSQL. The report service renders stored data and the annotated image into a PDF.
