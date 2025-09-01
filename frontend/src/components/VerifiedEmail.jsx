import React from "react";
import { useNavigate } from "react-router-dom";

export default function VerifiedEmail() {
    const navigate = useNavigate();

    return (
        <section className="min-h-screen flex flex-col justify-center items-center bg-gradient-to-b from-black to-gray-900 text-white px-4">
            <div className="bg-gray-800 p-10 rounded-2xl shadow-2xl max-w-md w-full text-center relative overflow-hidden">
                {/* ✅ BIG CHECKMARK ICON */}
                <div className="text-6xl text-green-400 mb-4 animate-pulse">✅</div>

                {/* ✨ GLOW ANIMATION */}
                <div className="absolute inset-0 bg-green-500 opacity-10 blur-2xl animate-pulse z-0"></div>

                {/* ✅ TEXT */}
                <h1 className="text-3xl font-bold mb-2 relative z-10">Email Verified</h1>
                <p className="text-gray-300 mb-6 relative z-10">
                    Your account is ready. You can now log in and start splitting tracks.
                </p>

                {/* ✅ BUTTON */}
                <button
                    onClick={() => navigate("/login")}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 transition rounded-lg font-semibold w-full relative z-10"
                >
                    Go to Login
                </button>
            </div>
        </section>
    );
}
