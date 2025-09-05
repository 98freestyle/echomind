import React, { useEffect, useContext, useState } from "react";
import { AuthContext } from "../context/AuthContext.jsx";
import { useSearchParams, useNavigate } from "react-router-dom";
import confetti from "canvas-confetti";

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
            .then((res) => res.json())
            .then((data) => {
                if (data.success) {
                    const { email } = data;
                    setUser({ email, is_premium: true });
                    localStorage.setItem("user", JSON.stringify({ email, is_premium: true }));
                    setMessage("🎉 Your account is now Premium!");

                    // Trigger confetti once on success
                    confetti({
                        particleCount: 150,
                        spread: 70,
                        origin: { y: 0.6 },
                    });
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
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-900 to-black text-white px-4">
            <div className="text-center">
                {loading ? (
                    <p className="text-lg">Upgrading your account...</p>
                ) : (
                    <p className="text-lg animate-fade-in font-bold text-xl">{message}</p>
                )}
                <button
                    onClick={() => navigate("/dashboard")}
                    className="mt-4 px-4 py-2 bg-indigo-600 rounded hover:bg-indigo-700 transition"
                >
                    Go to Dashboard
                </button>
            </div>
        </div>
    );
}
