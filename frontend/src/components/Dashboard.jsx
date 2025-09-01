import React, { useContext } from "react";
import { AuthContext } from "../context/AuthContext.jsx";

export default function Dashboard() {
    const { user } = useContext(AuthContext);

    return (
        <div className="min-h-screen bg-gradient-to-b from-gray-900 to-black text-white px-6 py-24 flex items-center justify-center">
            <div className="bg-gray-800/80 border border-gray-700 rounded-2xl shadow-xl max-w-xl w-full p-8 text-center backdrop-blur-md">
                <div className="text-5xl mb-4 animate-pulse">👋</div>
                <h1 className="text-3xl font-bold mb-2">Welcome, {user.email}</h1>
                <p className="text-gray-300">
                    You’re logged in and ready to start splitting tracks.
                </p>
            </div>
        </div>
    );
}
