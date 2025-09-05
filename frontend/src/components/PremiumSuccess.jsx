import React, { useEffect, useContext, useState } from "react";
import { AuthContext } from "../context/AuthContext.jsx";
import { useSearchParams, useNavigate } from "react-router-dom";

export default function PremiumSuccess() {
    const { setUser } = useContext(AuthContext);
    const [loading, setLoading] = useState(true);
    const [message, setMessage] = useState("");
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();

    useEffect(() => {
        const sessionId = searchParams.get("session_id");
        if (!sessionId) {
            setMessage("Missing session ID.");
            setLoading(false);
            return;
        }

        fetch(`${import.meta.env.VITE_BASE_URL}/validate-session`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const { email } = data;
                    setUser({ email, is_premium: true });
                    localStorage.setItem("user", JSON.stringify({ email, is_premium: true }));
                    setMessage("🎉 Your account is now Premium!");
                } else {
                    setMessage(data.error || "Something went wrong.");
                }
            })
            .catch(() => {
                setMessage("Failed to validate session.");
            })
            .finally(() => setLoading(false));
    }, []);

    return (
        <div className="min-h-screen bg-gradient-to-br from-zinc-900 via-black to-zinc-800 text-white flex flex-col justify-center items-center px-6">
            <div className="bg-white/5 backdrop-blur-md p-8 rounded-2xl shadow-2xl border border-white/10 max-w-xl w-full text-center animate-fade-in">
                {loading ? (
                    <p className="text-lg text-gray-300">Upgrading your account...</p>
                ) : (
                    <>
                        <div className="text-6xl mb-4">💎</div>
                        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white mb-3">
                            {message}
                        </h1>
                        <p className="text-gray-400 mb-6">
                            You now have faster processing, more upload space, and priority access.
                        </p>
                        <button
                            onClick={() => navigate("/dashboard")}
                            className="px-5 py-3 rounded-xl bg-yellow-500 text-black font-semibold hover:bg-yellow-400 transition"
                        >
                            Go to Dashboard
                        </button>
                    </>
                )}
            </div>
        </div>
    );
}
