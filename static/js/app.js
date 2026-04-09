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

  if (!button) {
    return;
  }

  button.addEventListener("click", async () => {
    setButtonBusy(button, true, "Capturing vein...", "Mark Attendance");
    setFlash(
      flash,
      "Capturing from the Raspberry Pi camera. Keep the finger still.",
      "info"
    );

    try {
      const payload = await requestJson("/api/attendance/mark", { method: "POST" });
      setFlash(flash, payload.message, "success");

      resultCard.innerHTML = "";
      const label = document.createElement("p");
      label.className = "result-label";
      label.textContent = "Last response";
      const heading = document.createElement("h2");
      heading.textContent = payload.user?.full_name || "Attendance captured";
      const detail = document.createElement("p");
      const scoreText = payload.score != null ? `Score: ${payload.score}` : "";
      const timeText = payload.record?.timestamp ? ` | Time: ${payload.record.timestamp}` : "";
      detail.textContent = scoreText + timeText;
      resultCard.append(label, heading, detail);

      refreshPreviewImages();
      refreshAttendanceLog();
    } catch (error) {
      setFlash(flash, error.message, "error");

      resultCard.innerHTML = "";
      const label = document.createElement("p");
      label.className = "result-label";
      label.textContent = "Last response";
      const heading = document.createElement("h2");
      heading.textContent = "Scan failed";
      const detail = document.createElement("p");
      detail.textContent = error.message;
      resultCard.append(label, heading, detail);

      refreshPreviewImages();
    } finally {
      setButtonBusy(button, false, "Capturing vein...", "Mark Attendance");
    }
  });

  refreshPreviewImages();
  refreshAttendanceLog();
}

function initAdminPage() {
  const form = document.getElementById("enroll-form");
  const flash = document.getElementById("admin-status");

  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitButton = form.querySelector('button[type="submit"]');
      const formData = new FormData(form);
      const payload = Object.fromEntries(formData.entries());

      setButtonBusy(submitButton, true, "Capturing samples...", "Capture and Enroll");
      setFlash(
        flash,
        "Enrollment started. Hold the finger in the same position until capture completes.",
        "info"
      );

      try {
        const response = await requestJson("/api/admin/enroll", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setFlash(flash, response.message, "success");
        refreshPreviewImages();
        window.setTimeout(() => window.location.reload(), 900);
      } catch (error) {
        setFlash(flash, error.message, "error");
      } finally {
        setButtonBusy(submitButton, false, "Capturing samples...", "Capture and Enroll");
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
