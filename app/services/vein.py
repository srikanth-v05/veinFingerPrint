import re

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - handled gracefully at runtime
    cv2 = None

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:  # pragma: no cover - handled gracefully at runtime
    Image = None
    ImageFilter = None
    ImageOps = None


class VeinRecognitionService:
    TEMPLATE_SIZE = (320, 128)

    def __init__(self):
        self._orb = cv2.ORB_create(nfeatures=300) if cv2 is not None else None
        try:
            import skimage.feature  # noqa: F401
            self._has_skimage = True
        except ImportError:
            self._has_skimage = False

    def normalize_user_id(self, value):
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
        cleaned = cleaned.strip("-")
        return cleaned

    def extract_template(self, frame):
        gray = self._to_grayscale(frame)
        roi = self._extract_finger_roi(gray)
        if roi is None:
            raise RuntimeError(
                "Finger region could not be detected. Improve lighting and finger placement."
            )

        if cv2 is not None:
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(roi)
            blackhat = cv2.morphologyEx(
                clahe,
                cv2.MORPH_BLACKHAT,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)),
            )
            normalized = cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)
            denoised = cv2.GaussianBlur(normalized, (5, 5), 0)
        else:
            if Image is None or ImageFilter is None or ImageOps is None:
                raise RuntimeError(
                    "OpenCV or Pillow is required for finger-vein processing."
                )
            pil_roi = Image.fromarray(roi, mode="L")
            equalized = np.array(ImageOps.equalize(pil_roi))
            blackhat = self._blackhat(equalized, size=17)
            denoised = np.array(
                Image.fromarray(blackhat, mode="L").filter(
                    ImageFilter.GaussianBlur(radius=1.4)
                )
            )

        threshold_value = self._otsu_threshold(denoised)
        binary = np.where(denoised >= threshold_value, 255, 0).astype(np.uint8)
        if cv2 is not None:
            enhanced = cv2.addWeighted(denoised, 0.65, binary, 0.35, 0)
        else:
            enhanced = np.clip((denoised * 0.65) + (binary * 0.35), 0, 255).astype(
                np.uint8
            )
        return enhanced

    def extract_features(self, template):
        if self._has_skimage:
            from skimage.feature import hog
            features = hog(
                template,
                orientations=9,
                pixels_per_cell=(8, 8),
                cells_per_block=(2, 2),
                block_norm='L2-Hys',
                visualize=False,
                feature_vector=True,
            )
            norm = np.linalg.norm(features)
            return features / norm if norm > 0 else features
        else:
            flat = template.astype(np.float32).ravel()
            norm = np.linalg.norm(flat)
            return flat / norm if norm > 0 else flat

    def compare_features(self, feat1, feat2):
        if feat1.shape != feat2.shape:
            return 0.0
        score = float(np.dot(feat1, feat2))
        return float(np.clip(score, 0.0, 1.0))

    def compare_templates(self, query_template, reference_template):
        query = query_template.astype(np.float32)
        reference = reference_template.astype(np.float32)

        if cv2 is not None:
            correlation = float(
                cv2.matchTemplate(query, reference, cv2.TM_CCOEFF_NORMED)[0][0]
            )
        else:
            query_centered = query - np.mean(query)
            reference_centered = reference - np.mean(reference)
            denominator = float(
                np.linalg.norm(query_centered) * np.linalg.norm(reference_centered)
            )
            if denominator == 0.0:
                correlation = 1.0 if np.array_equal(query_template, reference_template) else 0.0
            else:
                correlation = float(
                    np.sum(query_centered * reference_centered) / denominator
                )
        query_binary = query > np.mean(query)
        reference_binary = reference > np.mean(reference)
        intersection = float(np.logical_and(query_binary, reference_binary).sum())
        union = float(np.logical_or(query_binary, reference_binary).sum()) or 1.0
        overlap = intersection / union

        orb_score = 0.0
        if self._orb is not None:
            kp1, des1 = self._orb.detectAndCompute(query_template, None)
            kp2, des2 = self._orb.detectAndCompute(reference_template, None)
            if des1 is not None and des2 is not None and kp1 and kp2:
                matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                matches = matcher.match(des1, des2)
                good = [match for match in matches if match.distance < 60]
                orb_score = len(good) / max(min(len(kp1), len(kp2)), 1)
                orb_score = min(orb_score, 1.0)

        # NOTE: the old "difference" term (1 - mean_abs_diff/255) was removed because
        # it measures overall brightness similarity, not vein structure — two fingers
        # with similar lighting would score high regardless of their vein pattern,
        # causing false-positive matches.
        if self._orb is not None:
            score = (correlation * 0.60) + (overlap * 0.25) + (orb_score * 0.15)
        else:
            score = (correlation * 0.72) + (overlap * 0.28)
        return round(max(0.0, min(score, 1.0)), 4)

    def _to_grayscale(self, frame):
        if frame.ndim == 2:
            return frame
        if cv2 is not None:
            # NoIR camera + NIR backlight: the NIR signal lands almost entirely
            # in the red channel.  Standard luminance weights (R×0.299 G×0.587
            # B×0.114) would dilute the vein signal by 70 %.  Extract the red
            # channel directly for maximum contrast.
            # OpenCV frame is BGR → channel index 2 is Red.
            return frame[:, :, 2].copy()

        # PIL fallback — frame is RGB, channel 0 is Red
        return frame[..., 0].copy()

    def _extract_finger_roi(self, gray):
        if cv2 is not None:
            blurred = cv2.GaussianBlur(gray, (7, 7), 0)
            _, thresholded = cv2.threshold(
                blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

            if np.count_nonzero(thresholded) < thresholded.size * 0.2:
                thresholded = cv2.bitwise_not(thresholded)

            contours, _ = cv2.findContours(
                thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                return None

            height, width = gray.shape[:2]
            center = np.array([width / 2.0, height / 2.0])

            def contour_score(contour):
                x, y, w, h = cv2.boundingRect(contour)
                area = float(w * h)
                contour_center = np.array([x + (w / 2.0), y + (h / 2.0)])
                distance_penalty = np.linalg.norm(contour_center - center)
                return area - (distance_penalty * 3.0)

            best = max(contours, key=contour_score)
            x, y, w, h = cv2.boundingRect(best)
        else:
            if Image is None or ImageFilter is None:
                raise RuntimeError("OpenCV or Pillow is required for image processing.")

            blurred = np.array(
                Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(radius=2))
            )
            threshold_value = self._otsu_threshold(blurred)
            mask = blurred >= threshold_value
            if np.count_nonzero(mask) < mask.size * 0.2:
                mask = ~mask

            row_strength = mask.mean(axis=1)
            col_strength = mask.mean(axis=0)
            active_rows = np.where(row_strength > max(0.05, row_strength.max() * 0.3))[0]
            active_cols = np.where(col_strength > max(0.05, col_strength.max() * 0.3))[0]
            if active_rows.size == 0 or active_cols.size == 0:
                return None

            y = int(active_rows[0])
            h = int(active_rows[-1] - active_rows[0] + 1)
            x = int(active_cols[0])
            w = int(active_cols[-1] - active_cols[0] + 1)
            height, width = gray.shape[:2]

        if w < width * 0.1 or h < height * 0.1:
            return None

        pad_x = int(w * 0.07)
        pad_y = int(h * 0.12)
        x0 = max(x + pad_x, 0)
        y0 = max(y + pad_y, 0)
        x1 = min(x + w - pad_x, width)
        y1 = min(y + h - pad_y, height)
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            return None

        if cv2 is not None:
            return cv2.resize(roi, self.TEMPLATE_SIZE, interpolation=cv2.INTER_AREA)

        if Image is None:
            raise RuntimeError("Pillow is required for template resizing.")

        resampling = (
            Image.Resampling.BILINEAR
            if hasattr(Image, "Resampling")
            else Image.BILINEAR
        )
        return np.array(
            Image.fromarray(roi, mode="L").resize(self.TEMPLATE_SIZE, resample=resampling)
        )

    def _blackhat(self, image, size):
        pil_image = Image.fromarray(image, mode="L")
        dilated = pil_image.filter(ImageFilter.MaxFilter(size=size))
        closed = dilated.filter(ImageFilter.MinFilter(size=size))
        closed_array = np.array(closed, dtype=np.int16)
        source_array = np.array(pil_image, dtype=np.int16)
        return np.clip(closed_array - source_array, 0, 255).astype(np.uint8)

    def _normalize(self, image):
        min_value = float(np.min(image))
        max_value = float(np.max(image))
        if max_value <= min_value:
            return np.zeros_like(image, dtype=np.uint8)
        normalized = (image - min_value) / (max_value - min_value)
        return np.clip(normalized * 255.0, 0, 255).astype(np.uint8)

    def _otsu_threshold(self, image):
        histogram = np.bincount(image.ravel(), minlength=256).astype(np.float64)
        total = image.size
        cumulative_sum = np.cumsum(histogram)
        cumulative_mean = np.cumsum(histogram * np.arange(256))
        global_mean = cumulative_mean[-1]

        best_threshold = 0
        best_variance = -1.0

        for threshold in range(256):
            weight_background = cumulative_sum[threshold]
            weight_foreground = total - weight_background
            if weight_background == 0 or weight_foreground == 0:
                continue

            mean_background = cumulative_mean[threshold] / weight_background
            mean_foreground = (
                global_mean - cumulative_mean[threshold]
            ) / weight_foreground
            between_variance = (
                weight_background
                * weight_foreground
                * (mean_background - mean_foreground) ** 2
            )
            if between_variance > best_variance:
                best_variance = between_variance
                best_threshold = threshold

        return best_threshold
