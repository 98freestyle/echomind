import React, { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

export default function Signup() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState(false);
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    const isValidEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");
        setSuccess(false);

        if (!email || !password) {
            setError("All fields are required.");
            return;
        }

        if (!isValidEmail(email)) {
            setError("Invalid email format.");
            return;
        }

        if (password.length < 6) {
            setError("Password must be at least 6 characters.");
            return;
        }

        if (password !== confirmPassword) {
            setError("Passwords do not match.");
            return;
        }

        setLoading(true);

        try {
            const res = await axios.post("http://127.0.0.1:5000/signup", {
                email,
                password
            });

            if (res.status === 200 && res.data?.user) {
                setSuccess(true);
                setEmail("");
                setPassword("");
                setConfirmPassword("");
            } else {
                setError("Unexpected response from server.");
            }

        } catch (err) {
            setError(err.response?.data?.error || "Signup failed.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-900 to-black text-white px-4">
            <form
                onSubmit={handleSubmit}
                className="bg-gray-800 p-8 rounded-lg w-full max-w-md space-y-4 shadow-lg"
            >
                <h2 className="text-2xl font-bold text-center">Sign Up</h2>

                {error && <div className="bg-red-600 p-2 rounded text-sm">{error}</div>}
                {success && (
                    <div className="bg-green-700 bg-opacity-90 p-4 rounded-lg text-sm shadow-lg text-white space-y-1 border border-green-500">
                        <div className="text-lg font-semibold">✅ You're almost there!</div>
                        <p>Check your inbox and verify your email to start using EchoMind.</p>
                    </div>
                )}

                <input
                    type="email"
                    placeholder="Email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                />
                <input
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                />
                <input
                    type="password"
                    placeholder="Confirm password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full p-2 bg-gray-900 rounded"
                />

                <button
                    type="submit"
                    disabled={loading}
                    className={`w-full bg-indigo-600 p-2 rounded font-semibold transition ${loading ? "opacity-50 cursor-not-allowed" : "hover:bg-indigo-700"}`}
                >
                    {loading ? (
                        <div className="flex justify-center items-center h-6 space-x-1">
                            {[...Array(5)].map((_, i) => (
                                <div
                                    key={i}
                                    className="w-1 bg-white rounded animate-pulse"
                                    style={{
                                        animationDelay: `${i * 0.15}s`,
                                        animationDuration: "1s",
                                        height: "100%",
                                        transformOrigin: "center bottom",
                                        animationName: "wavePulse"
                                    }}
                                />
                            ))}
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
                    ) : "Sign Up"}
                </button>
            </form>
        </div>
    );
}
