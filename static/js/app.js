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

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
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

function renderAttendanceLog(records) {
  const table = document.querySelector("#attendance-log-table tbody");
  if (!table) {
    return;
  }

  if (!records.length) {
    table.innerHTML = '<tr><td colspan="5" class="empty-cell">No attendance records yet.</td></tr>';
    return;
  }

  table.innerHTML = records
    .map(
      (row) => `
        <tr>
          <td>${row.timestamp}</td>
          <td>${row.user_id}</td>
          <td>${row.name}</td>
          <td>${row.status}</td>
          <td>${row.score}</td>
        </tr>
      `
    )
    .join("");
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
      resultCard.innerHTML = `
        <p class="result-label">Last response</p>
        <h2>${payload.user?.full_name || "Attendance captured"}</h2>
        <p>Score: ${payload.score ?? "-"}${payload.record?.timestamp ? ` | Time: ${payload.record.timestamp}` : ""}</p>
      `;
      refreshPreviewImages();
      refreshAttendanceLog();
    } catch (error) {
      setFlash(flash, error.message, "error");
      resultCard.innerHTML = `
        <p class="result-label">Last response</p>
        <h2>Scan failed</h2>
        <p>${error.message}</p>
      `;
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
