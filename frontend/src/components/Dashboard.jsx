import React, { useContext, useEffect, useState } from "react";
import { AuthContext } from "../context/AuthContext.jsx";
import axios from "axios";

export default function Dashboard() {
    const { user } = useContext(AuthContext);
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!user?.email) return;
        axios.get(`${import.meta.env.VITE_BASE_URL}/job-history`, {
            headers: {
                "X-User-Email": user.email
            }
        })
            .then((res) => setHistory(res.data))
            .catch(() => setHistory([]))
            .finally(() => setLoading(false));
    }, [user?.email]);

    return (
        <div className="min-h-screen bg-gradient-to-b from-gray-900 to-black text-white px-6 py-24 flex items-center justify-center">
            <div className="bg-gray-800/80 border border-gray-700 rounded-2xl shadow-xl max-w-xl w-full p-8 text-center backdrop-blur-md">
                <div className="text-5xl mb-4 animate-pulse">👋</div>
                <h1 className="text-3xl font-bold mb-2">Welcome, {user.email}</h1>
                <p className="text-gray-300">
                    You’re logged in and ready to start splitting tracks.
                </p>

                {/* Job History Section */}
                <div className="mt-10 text-left">
                    <h2 className="text-xl font-bold text-white mb-4">Recent Uploads</h2>
                    {loading ? (
                        <p className="text-gray-400 text-sm">Loading history...</p>
                    ) : history.length === 0 ? (
                        <p className="text-gray-500 text-sm italic">No jobs found yet.</p>
                    ) : (
                        <div className="space-y-4 text-sm">
                            {history.map((item, index) => (
                                <div
                                    key={index}
                                    className="bg-gray-800/70 border border-gray-700 rounded-lg p-4 text-white shadow"
                                >
                                    <div className="flex justify-between items-center">
                                        <span className="font-medium truncate max-w-[50%]">{item.filename}</span>
                                        <span className="text-gray-400">{item.date}</span>
                                    </div>
                                    <div className="mt-1 text-gray-300">
                                        <span className="font-medium text-indigo-400">{item.stems}</span> • {item.duration} min
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
