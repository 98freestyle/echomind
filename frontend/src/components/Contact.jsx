import React, { useState } from "react";

export default function Contact() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setStatus(null);

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
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-900 to-black text-white px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md bg-zinc-800 p-6 rounded shadow-md"
      >
        <h2 className="text-2xl font-bold mb-4 text-center">Contact Support</h2>
        <input
          type="text"
          placeholder="Your Name"
          className="w-full mb-3 px-3 py-2 rounded bg-zinc-700 text-white placeholder-gray-400"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          type="email"
          placeholder="Your Email"
          className="w-full mb-3 px-3 py-2 rounded bg-zinc-700 text-white placeholder-gray-400"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <textarea
          placeholder="What's the issue?"
          className="w-full mb-3 px-3 py-2 rounded bg-zinc-700 text-white placeholder-gray-400"
          rows="5"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          required
        ></textarea>
        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 bg-indigo-600 rounded hover:bg-indigo-700 transition"
        >
          {loading ? "Sending..." : "Send Message"}
        </button>
        {status && <p className="mt-4 text-sm text-center">{status}</p>}
      </form>
    </div>
  );
}
