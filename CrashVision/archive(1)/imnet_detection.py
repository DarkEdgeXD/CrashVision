import cv2
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.applications.efficientnet import preprocess_input
from sklearn.cluster import KMeans

# Load the multitask model for crash detection
model_path = 'best_model.keras'
multi_output_model = load_model(model_path)

# Load the COCO class labels (COCO names)
coco_names = open('./archive(1)/yolo/coco.names').read().strip().split("\n")

def get_dominant_color(roi):
    """Identifies the dominant color in a region of interest (ROI)."""
    if roi.size == 0:  # Check if ROI is empty
        return "Unknown", (0, 0, 0)
    
    pixels = roi.reshape(-1, 3)
    kmeans = KMeans(n_clusters=1, n_init=10)
    kmeans.fit(pixels)
    dominant_color = kmeans.cluster_centers_[0][::-1]  # Convert to RGB format

    color_ranges = {
        'Red': ([150, 0, 0], [255, 50, 50]),
        'Blue': ([0, 0, 150], [50, 50, 255]),
        'Green': ([0, 150, 0], [50, 255, 50]),
        'White': ([200, 200, 200], [255, 255, 255]),
        'Black': ([0, 0, 0], [50, 50, 50]),
        'Silver': ([160, 160, 160], [200, 200, 200]),
        'Yellow': ([200, 200, 0], [255, 255, 255, 50])
    }
    
    for color_name, (lower, upper) in color_ranges.items():
        if all(lower[i] <= dominant_color[i] <= upper[i] for i in range(3)):
            return color_name, dominant_color
    return "Unknown", dominant_color

def get_severity_color(severity):
    """Returns color based on severity level."""
    return {
        0: (128, 128, 128),  # Gray for no accident
        1: (0, 255, 0),      # Green for low severity
        2: (0, 255, 255),    # Yellow for medium severity
        3: (0, 0, 255)       # Red for high severity
    }.get(severity, (255, 255, 255))

def preprocess_frame(frame, target_size=(224, 224)):
    """Preprocess frame for model input."""
    resized = cv2.resize(frame, target_size)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    preprocessed = preprocess_input(rgb.astype(np.float32))
    return np.expand_dims(preprocessed, axis=0)

def draw_label(frame, text, position, bg_color=(0, 0, 0), text_color=(255, 255, 255)):
    """Draw text label with background on frame."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    thickness = 2
    padding = 5

    # Get text size
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    
    # Calculate background rectangle coordinates
    x, y = position
    bg_rect_pt1 = (x, y - text_height - 2 * padding)
    bg_rect_pt2 = (x + text_width + 2 * padding, y)
    
    # Draw background rectangle and text
    cv2.rectangle(frame, bg_rect_pt1, bg_rect_pt2, bg_color, -1)
    cv2.putText(frame, text, (x + padding, y - padding), font, font_scale, text_color, thickness)

# Start real-time video capture
cap = cv2.VideoCapture(0)

# Load YOLO model for vehicle detection
net = cv2.dnn.readNet("./archive(1)/yolo/yolov3.weights", "./archive(1)/yolo/yolov3.cfg")
layer_names = net.getLayerNames()
output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers().flatten()]

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_height, frame_width, _ = frame.shape

    # Preprocess frame for crash detection
    preprocessed_frame = preprocess_frame(frame)
    
    # Get predictions from both model outputs
    severity_pred, accident_pred = multi_output_model.predict(preprocessed_frame, verbose=0)
    
    # Get severity class (0-3) and accident probability
    severity = np.argmax(severity_pred[0])
    accident_prob = accident_pred[0][np.argmax(accident_pred[0])]
    
    accident_detected = accident_prob > 0.7 and severity > 0

    if accident_detected:
        # Perform YOLO detection for vehicles
        blob = cv2.dnn.blobFromImage(frame, 0.00392, (416, 416), (0, 0, 0), True, crop=False)
        net.setInput(blob)
        outs = net.forward(output_layers)

        class_ids = []
        confidences = []
        boxes = []

        for out in outs:
            for detection in out:
                scores = detection[5:]
                class_id = np.argmax(scores)
                confidence = scores[class_id]
                
                if confidence > 0.7:
                    # Filter out non-vehicle classes
                    if class_id not in range(1, 9):
                        continue
                    
                    center_x = int(detection[0] * frame_width)
                    center_y = int(detection[1] * frame_height)
                    w = int(detection[2] * frame_width)
                    h = int(detection[3] * frame_height)

                    x = int(center_x - w / 2)
                    y = int(center_y - h / 2)

                    # Ensure the bounding box coordinates are valid
                    if x < 0 or y < 0 or x + w > frame_width or y + h > frame_height:
                        continue

                    boxes.append([x, y, w, h])
                    confidences.append(float(confidence))
                    class_ids.append(class_id)

        indexes = cv2.dnn.NMSBoxes(boxes, confidences, 0.7, 0.4)

        # Draw global accident severity indicator
        severity_text = f"Accident Severity: {severity} (Confidence: {accident_prob:.2f})"
        draw_label(frame, severity_text, (10, 30))

        # Ensure the indexes is not empty and flatten it correctly
        if len(indexes) > 0:
            for i in indexes.flatten():
                x, y, w, h = boxes[i]

                # Get vehicle color in the bounding box area
                roi = frame[y:y+h, x:x+w]
                vehicle_color, dominant_rgb = get_dominant_color(roi)
                vehicle_type = coco_names[class_ids[i]]

                # Draw bounding box with severity color
                box_color = get_severity_color(severity)
                cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)

                # Create and draw individual vehicle label above the bounding box
                vehicle_label = f"{vehicle_type} ({vehicle_color})"
                draw_label(frame, vehicle_label, (x, y - 5), box_color)

    else:
        # Draw "No Accident" indicator
        draw_label(frame, "No Accident Detected", (10, 30))

    cv2.imshow('Vehicle Crash Detection', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()