import React from "react";
import { useNavigate } from "react-router-dom";

export default function VerifiedEmail() {
    const navigate = useNavigate();

    return (
        <section className="min-h-screen flex flex-col justify-center items-center bg-gradient-to-b from-gray-900 to-black text-white text-center px-4">
            <div className="max-w-md w-full">
                <div className="text-6xl mb-4">✅</div>
                <h1 className="text-3xl font-bold mb-2">Email verified</h1>
                <p className="text-gray-300 mb-6">
                    Your account is ready. You can log in and start splitting tracks.
                </p>
                <button
                    onClick={() => navigate("/login")}
                    className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 transition font-semibold w-full"
                >
                    Go to Login
                </button>
            </div>
        </section>
    );
}
