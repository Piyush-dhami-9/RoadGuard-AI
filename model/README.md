# RoadGuard model

Place trained Ultralytics YOLO11 segmentation weights at `model/weights/best.pt`. The backend expects four classes in this order: Pothole, Longitudinal Crack, Transverse Crack, Alligator Crack. Until weights are supplied, the API uses its OpenCV demo detector for a runnable end-to-end experience.
