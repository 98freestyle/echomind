import React, { useState } from "react";

export default function Contact() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  // ------------------------------------------------------------
  // Handle form submission → POST to backend support endpoint
  // ------------------------------------------------------------
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setStatus(null);

    try {
      const res = await fetch("https://echomind.cloud/support-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, message }),
      });

      const data = await res.json();
      setLoading(false);

      if (data.success) {
        setStatus("✅ Your message has been sent. We'll get back to you ASAP.");
        setName("");
        setEmail("");
        setMessage("");
      } else {
        setStatus(data.error || "❌ Something went wrong. Please try again later.");
      }
    } catch {
      setLoading(false);
      setStatus("❌ Failed to send. Please try again later.");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-900 to-black text-white px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md bg-gray-900/80 border border-white/10 p-6 rounded-2xl shadow-xl backdrop-blur-sm"
      >
        <h2 className="text-2xl font-bold mb-6 text-center">Contact Support</h2>

        <input
          type="text"
          placeholder="Your Name"
          className="w-full mb-4 px-4 py-2 rounded-lg bg-gray-800 border border-white/10 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />

        <input
          type="email"
          placeholder="Your Email"
          className="w-full mb-4 px-4 py-2 rounded-lg bg-gray-800 border border-white/10 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <textarea
          placeholder="What's the issue?"
          className="w-full mb-6 px-4 py-2 rounded-lg bg-gray-800 border border-white/10 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          rows="5"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          required
        ></textarea>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 rounded-lg bg-gradient-to-r from-indigo-500 to-fuchsia-600 font-semibold shadow hover:opacity-90 transition disabled:opacity-50"
        >
          {loading ? "Sending..." : "Send Message"}
        </button>

        {status && (
          <p className="mt-4 text-sm text-center text-gray-300">{status}</p>
        )}
      </form>
    </div>
  );
}
