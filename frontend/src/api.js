import axios from "axios";

const API_BASE = "http://127.0.0.1:5000"; // Flask dev server URL

export async function uploadFile(file, selectedStems, onProgress, userEmail) {
  try {
    const formData = new FormData();
    formData.append("file", file);
    selectedStems.forEach(stem => formData.append("stems", stem));

    const res = await axios.post(`${API_BASE}/upload`, formData, {
      headers: {
        "Content-Type": "multipart/form-data",
        ...(userEmail && { "X-User-Email": userEmail })
      },
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          const percent = Math.round((e.loaded * 100) / e.total);
          onProgress(percent);
        }
      }
    });

    return res.data;
  } catch (err) {
    throw new Error(err.response?.data?.error || "Upload failed.");
  }
}

export function streamJob(jobId, onMessage) {
  const evtSource = new EventSource(`${API_BASE}/stream/${jobId}`);
  evtSource.onmessage = (e) => {
    onMessage(e.data);
    if (e.data.includes("Job complete") || e.data.includes("Error")) {
      evtSource.close(); // ✅ Stop the stream after finishing
    }
  };
  return evtSource;
}

export async function downloadZip(jobId, onError) {
  try {
    const res = await axios.get(`${API_BASE}/download/${jobId}`, {
      responseType: "blob"
    });

    let filename = "download.zip";
    const header = res.headers["content-disposition"];
    if (header && header.includes("filename=")) {
      filename = header.split("filename=")[1].replace(/"/g, "");
    }

    const url = window.URL.createObjectURL(new Blob([res.data]));
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);

  } catch (err) {
    if (onError) onError("Download failed. Please try again.");
  }
}

// Stripe Checkout Session Creator
export async function createCheckoutSession(email) {
  try {
    if (!email) throw new Error("You must be logged in to upgrade.");
    const res = await axios.post(`${API_BASE}/create-checkout-session`, { email });
    if (!res.data?.url) throw new Error("Failed to create checkout session.");
    window.location.href = res.data.url; // redirect to Stripe Checkout
  } catch (err) {
    throw new Error(err.response?.data?.error || err.message || "Stripe checkout failed.");
  }
}
