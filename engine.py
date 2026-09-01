"""
AgroAI Scout — YOLO11 inference engine (ONNX Runtime, no torch required).
Detects field pests and crop/field condition classes.
"""
import cv2
import numpy as np
import onnxruntime as ort

CLASS_NAMES = {
    0: 'Aphids', 1: 'Cereal flies', 2: 'Cutworm caterpillars', 3: 'Grain beetles',
    4: 'Grasshoppers', 5: 'Leaf beetles', 6: 'Leaf miners', 7: 'Leafhoppers',
    8: 'Mole cricket', 9: 'Nematodes', 10: 'Spider mites', 11: 'Stem flies',
    12: 'Thrips', 13: 'Weevils', 14: 'Wireworms', 15: 'Bedbugs',
    16: 'Damaged field', 17: 'Healthy field', 18: 'Plowed field',
    19: 'Stressed field', 20: 'May beetle', 21: 'Trash / debris field',
}

# Field-condition classes vs. pest classes — used by the UI to group results
FIELD_CLASSES = {16, 17, 18, 19, 21}

# Deterministic, readable color per class (HUD-style palette)
_PALETTE = [
    '#E8B93F', '#E2572B', '#4F8F7D', '#5FB0E0', '#C9724D', '#8F6FE0',
    '#E0A2C9', '#7FBF4A', '#D9D25A', '#B0745A', '#5AD9C0', '#E07F5F',
    '#9AA6E8', '#D95FA0', '#7ED9E0', '#C4E85F',
]
CLASS_COLORS = {i: _PALETTE[i % len(_PALETTE)] for i in CLASS_NAMES}
CLASS_COLORS[17] = '#6FCF6F'  # healthy field -> green
CLASS_COLORS[16] = '#E24444'  # damaged field -> red
CLASS_COLORS[19] = '#E8A23F'  # stressed field -> amber

INPUT_SIZE = 640


def letterbox(img, new_shape=640, color=(114, 114, 114)):
    h, w = img.shape[:2]
    r = min(new_shape / h, new_shape / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top = (new_shape - nh) // 2
    bottom = new_shape - nh - top
    left = (new_shape - nw) // 2
    right = new_shape - nw - left
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return padded, r, left, top


def hex_to_bgr(h):
    h = h.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


class Detector:
    def __init__(self, model_path='best.onnx'):
        self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name

    def infer(self, img_bgr, conf_thres=0.35, iou_thres=0.45):
        h0, w0 = img_bgr.shape[:2]
        padded, r, pad_x, pad_y = letterbox(img_bgr, INPUT_SIZE)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]

        out = self.session.run(None, {self.input_name: blob})[0]  # (1, 26, 8400)
        pred = out[0].T  # (8400, 26)

        boxes_xywh = pred[:, :4]
        scores_all = pred[:, 4:]
        class_ids = np.argmax(scores_all, axis=1)
        confs = scores_all[np.arange(len(scores_all)), class_ids]

        keep = confs > conf_thres
        boxes_xywh, confs, class_ids = boxes_xywh[keep], confs[keep], class_ids[keep]
        if len(boxes_xywh) == 0:
            return []

        cx, cy, w, h = boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
        x1 = np.clip((cx - w / 2 - pad_x) / r, 0, w0)
        y1 = np.clip((cy - h / 2 - pad_y) / r, 0, h0)
        x2 = np.clip((cx + w / 2 - pad_x) / r, 0, w0)
        y2 = np.clip((cy + h / 2 - pad_y) / r, 0, h0)
        boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

        idxs = cv2.dnn.NMSBoxes(
            [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes_xyxy],
            confs.tolist(), conf_thres, iou_thres,
        )
        results = []
        if len(idxs) > 0:
            for i in np.array(idxs).flatten():
                cid = int(class_ids[i])
                results.append({
                    'class_id': cid,
                    'class_name': CLASS_NAMES.get(cid, str(cid)),
                    'is_field': cid in FIELD_CLASSES,
                    'confidence': round(float(confs[i]), 4),
                    'box': [round(float(v), 1) for v in boxes_xyxy[i]],
                    'color': CLASS_COLORS.get(cid, '#E8B93F'),
                })
        results.sort(key=lambda d: -d['confidence'])
        return results

    def draw(self, img_bgr, detections):
        out = img_bgr.copy()
        for d in detections:
            x1, y1, x2, y2 = [int(v) for v in d['box']]
            color = hex_to_bgr(d['color'])
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"{d['class_name']} {d['confidence']*100:.0f}%"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ytxt = max(y1, th + 6)
            cv2.rectangle(out, (x1, ytxt - th - 6), (x1 + tw + 6, ytxt), color, -1)
            cv2.putText(out, label, (x1 + 3, ytxt - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (15, 15, 15), 1, cv2.LINE_AA)
        return out
