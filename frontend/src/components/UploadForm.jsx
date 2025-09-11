import React, { useState, useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import { uploadFile, streamJob } from "../api";
import axios from "axios";
import { useContext } from "react";
import { AuthContext } from "../context/AuthContext.jsx";

export default function UploadForm() {
  // Core upload state
  const [file, setFile] = useState(null);
  const [stems, setStems] = useState(["vocals", "other"]);
  const [status, setStatus] = useState("");
  const [jobId, setJobId] = useState(null);
  const [done, setDone] = useState(false);
  const [showPreview, setShowPreview] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [evtSource, setEvtSource] = useState(null);
  const [error, setError] = useState("");

  // Audio preview controls
  const waveRefs = useRef({});
  const [playingStates, setPlayingStates] = useState({});
  const [volumes, setVolumes] = useState({});
  const [isPlayingAll, setIsPlayingAll] = useState(false);

  // User context and premium status
  const { user } = useContext(AuthContext);
  const [isPremium, setIsPremium] = useState(false);

  // Download preparation states
  const [isZipReady, setIsZipReady] = useState(false);
  const [isPreparingZip, setIsPreparingZip] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);

  // Usage tracking
  const [usedMin, setUsedMin] = useState(0);
  const [limitMin, setLimitMin] = useState(150);

  // File validation state
  const [isCheckingFile, setIsCheckingFile] = useState(false);

  // Configuration constants
  const POLLING_INTERVAL = 3000; // 3 seconds
  const POLLING_TIMEOUT = 120000; // 2 minutes  
  const USAGE_WARNING_THRESHOLD = 85; // 85%

  // Fetch user usage data from backend
  const fetchUsage = async () => {
    try {
      const res = await axios.get(`${import.meta.env.VITE_BASE_URL}/usage`, {
        headers: {
          ...(user?.email && { "X-User-Email": user.email })
        }
      });
      setUsedMin(res.data.used_min);
      setLimitMin(res.data.limit_min);
      setIsPremium(res.data.is_premium);
    } catch (err) {
      console.error("Failed to fetch usage", err);
    }
  };

  useEffect(() => {
    fetchUsage();
  }, []);

  // Get audio file duration before upload to check quota
  const getAudioDuration = (file) => {
    return new Promise((resolve, reject) => {
      const audio = document.createElement('audio');
      const url = URL.createObjectURL(file);

      audio.addEventListener('loadedmetadata', () => {
        URL.revokeObjectURL(url);
        resolve(audio.duration);
      });

      audio.addEventListener('error', () => {
        URL.revokeObjectURL(url);
        reject(new Error('Could not load audio file'));
      });

      audio.src = url;
    });
  };

  // Validate file against quota before allowing upload
  const checkQuotaBeforeUpload = async (selectedFile) => {
    setIsCheckingFile(true);
    setError("");

    try {
      const durationSeconds = await getAudioDuration(selectedFile);
      const durationMinutes = durationSeconds / 60;
      const wouldExceedQuota = (usedMin + durationMinutes) > limitMin;
      const remainingMin = limitMin - usedMin;

      if (wouldExceedQuota) {
        setError(
          `Upload blocked: This ${durationMinutes.toFixed(1)}-minute file would exceed your ${limitMin}-minute limit. ${remainingMin.toFixed(1)} minutes remaining.`
        );
        setIsCheckingFile(false);
        return false;
      }

      setIsCheckingFile(false);
      return true;
    } catch (err) {
      console.error("Error checking file duration:", err);
      setError("❌ Could not analyze audio file. Please ensure it's a valid audio format.");
      setIsCheckingFile(false);
      return false;
    }
  };

  const toggleStem = (stem) => {
    setStems((prev) =>
      prev.includes(stem) ? prev.filter((s) => s !== stem) : [...prev, stem]
    );
  };

  // Check if processed files are ready for download
  const checkZipStatus = async (jobId) => {
    try {
      const response = await axios.get(`${import.meta.env.VITE_BASE_URL}/download-link/${jobId}`);
      return response.status === 200 && response.data?.url;
    } catch (err) {
      if (err.response?.status === 404 || err.response?.status === 400) {
        return false;
      }
      console.error("Failed to check zip status:", err);
      return false;
    }
  };

  // Poll backend until zip file is ready
  const pollZipReadiness = (jobId) => {
    setIsPreparingZip(true);

    const pollInterval = setInterval(async () => {
      const ready = await checkZipStatus(jobId);
      if (ready) {
        setIsZipReady(true);
        setIsPreparingZip(false);
        clearInterval(pollInterval);
      }
    }, POLLING_INTERVAL);

    // Fallback timeout to prevent infinite polling
    setTimeout(() => {
      clearInterval(pollInterval);
      if (!isZipReady) {
        console.log("Zip polling timeout - assuming ready");
        setIsZipReady(true);
        setIsPreparingZip(false);
      }
    }, POLLING_TIMEOUT);
  };

  // Main upload handler - validates quota then starts upload
  const startUpload = async (selectedFile) => {
    if (!selectedFile) return;

    // Block upload if it would exceed quota
    const canUpload = await checkQuotaBeforeUpload(selectedFile);
    if (!canUpload) return;

    setFile(selectedFile);
    setUploading(true);
    setStatus("Uploading...");
    setDone(false);
    setShowPreview(true);
    setError("");

    // Reset download states for new upload
    setIsZipReady(false);
    setIsPreparingZip(false);
    setIsDownloading(false);

    console.log("Logged in as:", user?.email);

    let res;
    try {
      res = await uploadFile(selectedFile, stems, null, user?.email);
      if (!res?.job_id) throw new Error("No job ID received.");
    } catch (err) {
      console.error(err);
      const backendMsg = err.response?.data?.error || "Upload failed.";
      setError(backendMsg);
      setUploading(false);
      return;
    }

    setJobId(res.job_id);
    setStatus("Processing...");

    // Listen for processing updates via server-sent events
    const es = streamJob(res.job_id, (msg) => {
      setStatus(msg);
      if (msg.includes("Job complete")) {
        setStatus("Previews ready!");
        setTimeout(() => {
          setDone(true);
          setUploading(false);
          fetchUsage(); // Refresh usage after processing
          pollZipReadiness(res.job_id); // Start checking for zip
        }, 500);
      }
    });

    setEvtSource(es);
  };

  // Handle final download and reset UI
  const handleDownload = async () => {
    if (!jobId || !isZipReady) return;

    try {
      setIsDownloading(true);

      const res = await axios.get(`${import.meta.env.VITE_BASE_URL}/download-link/${jobId}`);
      const downloadUrl = `${import.meta.env.VITE_BASE_URL}${res.data.url}`;

      // Reset all state immediately for new upload
      setIsDownloading(false);
      setFile(null);
      setJobId(null);
      setDone(false);
      setStatus("");
      setShowPreview(false);
      setStems(["vocals", "other"]);
      setUploading(false);
      setPlayingStates({});
      setVolumes({});
      setIsZipReady(false);
      setIsPreparingZip(false);

      // Trigger browser download
      window.location.href = downloadUrl;

    } catch (err) {
      setIsDownloading(false);
      setError("Download failed. Try again.");
      console.error(err);
    }
  };

  const handleFileSelect = async (e) => {
    console.log("FILE SELECTED");
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;

    setError("");
    await startUpload(selectedFile);
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) await startUpload(droppedFile);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  // Cleanup event sources and waveforms on unmount
  useEffect(() => {
    return () => {
      if (evtSource) evtSource.close();
      Object.values(waveRefs.current).forEach((ws) => ws.destroy());
    };
  }, [evtSource]);

  // Create waveform visualization for each stem
  const createWaveform = (url, stem) => {
    const container = document.getElementById(`waveform-${stem}`);
    if (!container) return;

    if (waveRefs.current[stem]) {
      waveRefs.current[stem].destroy();
    }

    waveRefs.current[stem] = WaveSurfer.create({
      container: container,
      waveColor: "#4F46E5",
      progressColor: "#22C55E",
      cursorColor: "#FFFFFF",
      height: 80,
      barWidth: 2,
      responsive: true,
      volume: volumes[stem] ?? 1,
    });

    waveRefs.current[stem].load(url);
  };

  // Initialize waveforms when preview is ready
  useEffect(() => {
    if (done && showPreview && jobId) {
      stems.forEach((stem) => {
        const url = `${import.meta.env.VITE_BASE_URL}/preview/${jobId}/${stem}`;
        createWaveform(url, stem);
      });
    }
  }, [done, showPreview, jobId]);

  // Toggle play/pause for individual stems
  const toggleStemPlay = (stem) => {
    const ws = waveRefs.current[stem];
    if (!ws) return;
    if (playingStates[stem]) {
      ws.pause();
      setPlayingStates((prev) => ({ ...prev, [stem]: false }));
    } else {
      ws.play();
      setPlayingStates((prev) => ({ ...prev, [stem]: true }));
    }
  };

  const handleVolumeChange = (stem, value) => {
    const vol = Math.max(0, Math.min(1, value));
    setVolumes((prev) => ({ ...prev, [stem]: vol }));
    if (waveRefs.current[stem]) {
      waveRefs.current[stem].setVolume(vol);
    }
  };

  // Handle volume slider drag interaction
  const startDrag = (stem, e) => {
    const bar = e.currentTarget;

    const updateVolume = (event) => {
      const rect = bar.getBoundingClientRect();
      const y = event.clientY - rect.top;
      const height = rect.height;
      const newVol = 1 - y / height;
      handleVolumeChange(stem, newVol);
    };

    updateVolume(e);

    const moveHandler = (event) => updateVolume(event);
    const upHandler = () => {
      window.removeEventListener("mousemove", moveHandler);
      window.removeEventListener("mouseup", upHandler);
    };

    window.addEventListener("mousemove", moveHandler);
    window.addEventListener("mouseup", upHandler);
  };

  const usagePercent = Math.min(100, Math.round((usedMin / limitMin) * 100));

  // Determine download button state and styling
  const getDownloadButtonState = () => {
    if (!done) return { disabled: true, text: "Processing...", className: "bg-gray-600" };
    if (isPreparingZip) return { disabled: true, text: "Preparing Download...", className: "bg-yellow-600" };
    if (isZipReady && !isDownloading) return { disabled: false, text: "Download Zip", className: "bg-green-600 hover:bg-green-700" };
    if (isDownloading) return { disabled: true, text: "Downloading...", className: "bg-blue-600" };
    return { disabled: true, text: "Preparing...", className: "bg-gray-600" };
  };

  const downloadButtonState = getDownloadButtonState();

  return (
    <div
      className="bg-gray-800 bg-opacity-50 p-6 rounded-xl shadow-lg"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {/* Premium account badge */}
      {isPremium && (
        <div className="w-full mb-6">
          <div className="relative w-full bg-[#1f1f1f] border border-yellow-500 rounded-xl shadow-lg px-6 py-3 flex items-center justify-between overflow-hidden">
            <div className="flex items-center space-x-3">
              <div className="w-3 h-3 rounded-full bg-yellow-400 animate-pulse"></div>
              <span className="text-yellow-300 font-semibold tracking-wide text-sm uppercase">
                Premium Account
              </span>
            </div>
            <span className="text-xs text-yellow-500 italic">
              3GB Limit • Priority Queue • Clean Audio Previews
            </span>
            <div className="absolute inset-0 pointer-events-none opacity-5 bg-[url('/gold-texture.png')] bg-cover bg-center" />
          </div>
        </div>
      )}

      {/* Usage progress bar */}
      <div className="mb-4">
        <p className="text-sm text-gray-200 mb-1">
          📊 Usage: {usedMin} min / {limitMin} min ({usagePercent}%)
        </p>
        <div className="w-full h-3 bg-gray-600 rounded">
          <div
            className={`h-3 rounded transition-all duration-300 ${usagePercent < 60
              ? "bg-green-500"
              : usagePercent < 90
                ? "bg-yellow-400"
                : "bg-red-500"
              }`}
            style={{ width: `${usagePercent}%` }}
          ></div>
        </div>
        {usagePercent >= USAGE_WARNING_THRESHOLD && (
          <p className="text-sm text-red-500 font-medium mt-1">
            ⚠️ You're close to your weekly limit!
          </p>
        )}
        <p className="text-xs text-gray-400 mt-1">
          Usage resets every Monday at 12:00 AM (AEST)
        </p>
      </div>

      {/* Error messages */}
      {error && (
        <div className="mb-4 p-3 bg-red-600 bg-opacity-80 rounded text-white text-sm">
          {error}
        </div>
      )}

      {/* File upload area and stem selection */}
      {!done && !uploading && (
        <>
          <label className={`flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded-lg cursor-pointer transition ${isCheckingFile
            ? 'border-yellow-400 bg-yellow-50 bg-opacity-10'
            : 'border-gray-500 hover:border-indigo-400'
            }`}>
            {isCheckingFile ? (
              <div className="text-center">
                <div className="animate-spin w-6 h-6 border-2 border-yellow-400 border-t-transparent rounded-full mx-auto mb-2"></div>
                <p className="text-yellow-300 text-sm">Analyzing file...</p>
              </div>
            ) : (
              <p className="text-gray-300 text-sm mb-2">
                Drag & Drop or Click to Select a File
              </p>
            )}
            <input
              type="file"
              onChange={handleFileSelect}
              className="hidden"
              disabled={isCheckingFile}
            />
          </label>

          <div className="flex flex-wrap gap-4 justify-center mt-4">
            {["vocals", "drums", "bass", "other"].map((stem) => (
              <label key={stem} className="text-sm">
                <input
                  type="checkbox"
                  className="mr-2"
                  checked={stems.includes(stem)}
                  onChange={() => toggleStem(stem)}
                  disabled={uploading || jobId !== null || isCheckingFile}
                />
                {stem.charAt(0).toUpperCase() + stem.slice(1)}
              </label>
            ))}
          </div>
        </>
      )}

      {/* Processing animation */}
      {uploading && !done && (
        <div className="flex flex-col items-center justify-center mt-8">
          <div className="flex space-x-1 h-8">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="w-2 bg-indigo-500 rounded animate-pulse"
                style={{
                  animationDelay: `${i * 0.15}s`,
                  animationDuration: "1s",
                  height: "100%",
                  transformOrigin: "center bottom",
                  animationName: "wavePulse",
                }}
              />
            ))}
          </div>
          <p className="mt-4 text-gray-300 text-sm">{status}</p>

          <style>
            {`
              @keyframes wavePulse {
                0%, 100% { transform: scaleY(0.3); opacity: 0.5; }
                50% { transform: scaleY(1); opacity: 1; }
              }
              .animate-pulse {
                animation: wavePulse 1s ease-in-out infinite;
              }
            `}
          </style>
        </div>
      )}

      {/* Download section with preview */}
      {done && (
        <div className="mt-6">
          <button
            onClick={handleDownload}
            disabled={downloadButtonState.disabled}
            className={`px-6 py-2 rounded-lg font-medium transition-colors ${downloadButtonState.className} ${downloadButtonState.disabled ? 'cursor-not-allowed opacity-75' : 'cursor-pointer'
              }`}
          >
            {downloadButtonState.text}
          </button>

          {showPreview && (
            <div className="mt-6 bg-gray-900 p-4 rounded-lg">
              <div className="mb-4 flex justify-between items-center">
                <h3 className="text-white text-xl font-semibold">Preview Stems</h3>
                <button
                  onClick={() => {
                    const shouldPlay = !isPlayingAll;
                    setIsPlayingAll(shouldPlay);
                    stems.forEach((stem) => {
                      const ws = waveRefs.current[stem];
                      if (ws) {
                        ws.seekTo(0);
                        shouldPlay ? ws.play() : ws.pause();
                      }
                    });
                  }}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded-lg font-semibold text-white transition"
                >
                  {isPlayingAll ? "⏹ Stop All" : "▶️ Play All in Sync"}
                </button>
              </div>

              {/* Individual stem controls with waveforms */}
              {stems.map((stem) => (
                <div key={stem} className="mb-6 flex items-center space-x-3">
                  <div className="min-w-[60px] text-sm text-white font-medium capitalize">
                    {stem}
                  </div>

                  <button
                    onClick={() => {
                      if (isPlayingAll) return;
                      toggleStemPlay(stem);
                    }}
                    className="bg-gray-700 hover:bg-gray-600 p-2 rounded-full flex items-center justify-center"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="w-6 h-6 text-white"
                      fill="currentColor"
                      viewBox="0 0 24 24"
                    >
                      {playingStates[stem] ? (
                        <path d="M6 4h4v16H6zm8 0h4v16h-4z" />
                      ) : (
                        <path d="M8 5v14l11-7z" />
                      )}
                    </svg>
                  </button>

                  <div
                    id={`waveform-${stem}`}
                    className="flex-1 bg-black rounded"
                  ></div>

                  {/* Volume slider */}
                  <div
                    className="relative w-8 h-32 bg-gray-700 rounded-lg cursor-pointer flex flex-col justify-end items-center overflow-hidden"
                    onMouseDown={(e) => startDrag(stem, e)}
                  >
                    <div
                      className="absolute bottom-0 left-0 right-0 rounded-lg transition-all duration-200"
                      style={{
                        height: `${(volumes[stem] ?? 1) * 100}%`,
                        background: "linear-gradient(to top, #22C55E, #4F46E5)",
                      }}
                    ></div>
                    <span className="relative text-xs text-white font-bold mb-1 z-10">
                      {Math.round((volumes[stem] ?? 1) * 100)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}