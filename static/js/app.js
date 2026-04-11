function setFlash(element, message, variant) {
  if (!element) {
    return;
  }

  element.textContent = message;
  element.className = `flash ${variant}`;
}

function setButtonBusy(button, busy, busyLabel, idleLabel) {
  if (!button) {
    return;
  }

  button.disabled = busy;
  button.textContent = busy ? busyLabel : idleLabel;
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

async function requestJson(url, options = {}) {
  const headers = { ...options.headers };
  if (options.method && options.method.toUpperCase() !== "GET") {
    headers["X-CSRF-Token"] = getCsrfToken();
  }
  const response = await fetch(url, { ...options, headers });
  let payload = {};

  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.message || "Request failed.");
  }

  return payload;
}

function focusLabel(val) {
  // 0 = Auto; otherwise show approximate distance in cm
  if (val === 0) return "Auto";
  return "~" + Math.round(100 / val) + " cm";
}

function makeFocusHandler(sliderId, displayId) {
  const slider = document.getElementById(sliderId);
  const display = document.getElementById(displayId);
  if (!slider || !display) return;

  let focusTimer = null;
  slider.addEventListener("input", () => {
    const val = parseFloat(slider.value);
    display.textContent = focusLabel(val);
    clearTimeout(focusTimer);
    focusTimer = setTimeout(async () => {
      try {
        await requestJson("/api/camera/focus", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ focus: val }),
        });
      } catch (_) {}
    }, 150);
  });
}

function refreshPreviewImages() {
  document.querySelectorAll("img[data-preview]").forEach((image) => {
    const name = image.dataset.preview;
    image.src = `/captures/${name}.png?t=${Date.now()}`;
  });
}

function createTextCell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

function renderAttendanceLog(records) {
  const tbody = document.querySelector("#attendance-log-table tbody");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (!records.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty-cell";
    td.textContent = "No attendance records yet.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  records.forEach((row) => {
    const tr = document.createElement("tr");
    [row.timestamp, row.user_id, row.name, row.status, row.score].forEach((val) => {
      tr.appendChild(createTextCell(val ?? ""));
    });
    tbody.appendChild(tr);
  });
}

async function refreshAttendanceLog() {
  try {
    const payload = await requestJson("/api/attendance/log?limit=8");
    renderAttendanceLog(payload.records || []);
  } catch (error) {
    console.error(error);
  }
}

function initAttendancePage() {
  const button = document.getElementById("mark-attendance-button");
  const flash = document.getElementById("attendance-status");
  const resultCard = document.getElementById("attendance-result");

  const modal = document.getElementById("capture-modal");
  const closeModalBtn = document.getElementById("close-modal-btn");
  const liveFeed = document.getElementById("live-feed-img");
  const brightnessSlider = document.getElementById("brightness-slider");
  const brightnessDisplay = document.getElementById("brightness-value-display");
  const modalCaptureBtn = document.getElementById("modal-capture-btn");
  const modalStatus = document.getElementById("modal-status");

  if (!button) {
    return;
  }

  function openCaptureModal() {
    modal.classList.remove("hidden");
    liveFeed.src = "/api/camera/stream";
  }

  function closeCaptureModal() {
    modal.classList.add("hidden");
    liveFeed.src = "";
  }

  function showCaptureResult(payload, isError) {
    if (isError) {
      setFlash(flash, payload.message || payload, "error");
    } else {
      setFlash(flash, payload.message, "success");
    }
    resultCard.innerHTML = "";
    const label = document.createElement("p");
    label.className = "result-label";
    label.textContent = "Last response";
    const heading = document.createElement("h2");
    heading.textContent = isError ? "Scan failed" : (payload.user?.full_name || "Attendance captured");
    const detail = document.createElement("p");
    if (!isError) {
      const scoreText = payload.score != null ? `Score: ${payload.score}` : "";
      const timeText = payload.record?.timestamp ? ` | Time: ${payload.record.timestamp}` : "";
      detail.textContent = scoreText + timeText;
    } else {
      detail.textContent = payload.message || payload;
    }
    resultCard.append(label, heading, detail);
  }

  // Debounced brightness update
  let brightnessTimer = null;
  brightnessSlider.addEventListener("input", () => {
    const val = parseInt(brightnessSlider.value, 10);
    brightnessDisplay.textContent = val > 0 ? `+${val}` : String(val);
    clearTimeout(brightnessTimer);
    brightnessTimer = setTimeout(async () => {
      try {
        await requestJson("/api/camera/brightness", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brightness: val }),
        });
      } catch (_) {}
    }, 150);
  });

  makeFocusHandler("focus-slider", "focus-value-display");

  button.addEventListener("click", () => {
    openCaptureModal();
  });

  closeModalBtn.addEventListener("click", () => {
    closeCaptureModal();
  });

  // Close on backdrop click
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeCaptureModal();
  });

  // Escape key closes modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeCaptureModal();
    }
  });

  modalCaptureBtn.addEventListener("click", async () => {
    setButtonBusy(modalCaptureBtn, true, "Capturing...", "Capture");
    setFlash(modalStatus, "Capturing from camera. Keep the finger still.", "info");

    try {
      const payload = await requestJson("/api/attendance/mark", { method: "POST" });
      closeCaptureModal();
      showCaptureResult(payload, false);
      refreshPreviewImages();
      refreshAttendanceLog();
    } catch (error) {
      setFlash(modalStatus, error.message, "error");
      refreshPreviewImages();
    } finally {
      setButtonBusy(modalCaptureBtn, false, "Capturing...", "Capture");
    }
  });

  refreshPreviewImages();
  refreshAttendanceLog();
}

function initAdminPage() {
  const form = document.getElementById("enroll-form");
  const flash = document.getElementById("admin-status");

  const enrollModal = document.getElementById("enroll-modal");
  const closeEnrollBtn = document.getElementById("close-enroll-modal-btn");
  const enrollFeed = document.getElementById("enroll-feed-img");
  const enrollBrightnessSlider = document.getElementById("enroll-brightness-slider");
  const enrollBrightnessDisplay = document.getElementById("enroll-brightness-display");
  const startEnrollBtn = document.getElementById("start-enroll-btn");
  const enrollModalStatus = document.getElementById("enroll-modal-status");

  // Pending enrollment payload — set when form is submitted, consumed when
  // the user clicks "Start Enrollment" inside the modal.
  let pendingPayload = null;

  function openEnrollModal() {
    enrollModal.classList.remove("hidden");
    enrollFeed.src = "/api/camera/stream";
    setFlash(enrollModalStatus, "Position finger in the slot, then click Start Enrollment.", "info");
    startEnrollBtn.disabled = false;
    startEnrollBtn.textContent = "Start Enrollment";
  }

  function closeEnrollModal() {
    enrollModal.classList.add("hidden");
    enrollFeed.src = "";
    pendingPayload = null;
  }

  // Shared brightness slider (same endpoint as attendance page)
  let enrollBrightnessTimer = null;
  if (enrollBrightnessSlider) {
    enrollBrightnessSlider.addEventListener("input", () => {
      const val = parseInt(enrollBrightnessSlider.value, 10);
      enrollBrightnessDisplay.textContent = val > 0 ? `+${val}` : String(val);
      clearTimeout(enrollBrightnessTimer);
      enrollBrightnessTimer = setTimeout(async () => {
        try {
          await requestJson("/api/camera/brightness", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ brightness: val }),
          });
        } catch (_) {}
      }, 150);
    });
  }

  makeFocusHandler("enroll-focus-slider", "enroll-focus-display");

  if (closeEnrollBtn) {
    closeEnrollBtn.addEventListener("click", closeEnrollModal);
  }
  if (enrollModal) {
    enrollModal.addEventListener("click", (e) => {
      if (e.target === enrollModal) closeEnrollModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !enrollModal.classList.contains("hidden")) {
        closeEnrollModal();
      }
    });
  }

  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      pendingPayload = Object.fromEntries(formData.entries());
      openEnrollModal();
    });
  }

  if (startEnrollBtn) {
    startEnrollBtn.addEventListener("click", async () => {
      if (!pendingPayload) return;
      const payload = pendingPayload;
      const sampleCount = parseInt(payload.sample_count, 10) || 3;

      setButtonBusy(startEnrollBtn, true, "Capturing...", "Start Enrollment");
      setFlash(
        enrollModalStatus,
        `Capturing ${sampleCount} sample(s). Keep the finger completely still.`,
        "info"
      );

      try {
        const response = await requestJson("/api/admin/enroll", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        closeEnrollModal();
        setFlash(flash, response.message, "success");
        refreshPreviewImages();
        window.setTimeout(() => window.location.reload(), 900);
      } catch (error) {
        setFlash(enrollModalStatus, error.message, "error");
        setButtonBusy(startEnrollBtn, false, "Capturing...", "Start Enrollment");
      }
    });
  }

  document.querySelectorAll(".delete-user-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const userId = button.dataset.userId;
      const confirmed = window.confirm(`Remove user "${userId}"?`);
      if (!confirmed) {
        return;
      }

      setButtonBusy(button, true, "Removing...", "Remove");

      try {
        const response = await requestJson(`/api/admin/users/${userId}/delete`, {
          method: "POST",
        });
        setFlash(flash, response.message, "success");
        window.setTimeout(() => window.location.reload(), 600);
      } catch (error) {
        setFlash(flash, error.message, "error");
        setButtonBusy(button, false, "Removing...", "Remove");
      }
    });
  });

  refreshPreviewImages();
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;

  if (page === "attendance") {
    initAttendancePage();
  }

  if (page === "admin") {
    initAdminPage();
  }
});
