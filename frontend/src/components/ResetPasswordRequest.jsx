import React, { useState } from "react";
import axios from "axios";

export default function ResetPasswordRequest() {
    const [email, setEmail] = useState("");
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");
        setMessage("");
        setLoading(true);

        try {
            const res = await axios.post(`${import.meta.env.VITE_BASE_URL}/reset-password-request`, { email });

            if (res.data.success) {
                setMessage("✅ Password reset link sent to your email.");
                setEmail("");
            } else {
                setError("Something went wrong. Try again.");
            }
        } catch (err) {
            setError(err.response?.data?.error || "Request failed.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-900 to-black text-white px-4">
            <form onSubmit={handleSubmit} className="bg-gray-800/80 backdrop-blur-md border border-gray-700 p-8 rounded-2xl w-full max-w-md space-y-4 shadow-xl">
                <h2 className="text-2xl font-bold text-center">Reset Your Password</h2>

                {error && <div className="bg-red-600 p-2 rounded text-sm">{error}</div>}
                {message && <div className="bg-green-600 p-2 rounded text-sm">{message}</div>}

                <input
                    type="email"
                    placeholder="Enter your email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                    required
                />

                <button
                    type="submit"
                    disabled={loading}
                    className={`w-full bg-indigo-600 p-2 rounded font-semibold transition ${loading ? "opacity-50 cursor-not-allowed" : "hover:bg-indigo-700"
                        }`}
                >
                    {loading ? "Sending..." : "Send Reset Link"}
                </button>
            </form>
        </div>
    );
}
