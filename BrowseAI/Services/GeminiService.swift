import Foundation

/// Service that talks to the Gemini API.
///
/// Set your API key in `GeminiService.apiKey` at launch or via
/// an environment variable / config file before shipping.
actor GeminiService {
    static let shared = GeminiService()

    // TODO: Replace with your actual Gemini API key.
    // For production, load this from Keychain or a secure config.
    private var apiKey: String {
        ProcessInfo.processInfo.environment["GEMINI_API_KEY"] ?? ""
    }

    private let baseURL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    // MARK: - Public

    func sendMessage(
        _ userMessage: String,
        pageContent: String?,
        pageURL: String?,
        chatState: ChatState
    ) async {
        await MainActor.run { chatState.isGenerating = true }

        defer {
            Task { @MainActor in chatState.isGenerating = false }
        }

        // Build the prompt with optional page context
        var systemParts = "You are a helpful AI assistant built into a web browser. Be concise."
        if let url = pageURL, let content = pageContent, !content.isEmpty {
            let trimmed = String(content.prefix(4000))
            systemParts += "\n\nThe user is currently viewing: \(url)\nPage content (truncated):\n\(trimmed)"
        }

        let requestBody: [String: Any] = [
            "contents": [
                [
                    "role": "user",
                    "parts": [["text": systemParts + "\n\nUser: " + userMessage]]
                ]
            ],
            "generationConfig": [
                "temperature": 0.7,
                "maxOutputTokens": 1024
            ]
        ]

        guard let url = URL(string: "\(baseURL)?key=\(apiKey)") else {
            await MainActor.run {
                chatState.addAssistantMessage("Error: Invalid API configuration.")
            }
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")

        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: requestBody)
        } catch {
            await MainActor.run {
                chatState.addAssistantMessage("Error building request: \(error.localizedDescription)")
            }
            return
        }

        do {
            let (data, response) = try await URLSession.shared.data(for: request)

            guard let httpResponse = response as? HTTPURLResponse else {
                await MainActor.run {
                    chatState.addAssistantMessage("Error: Invalid response from server.")
                }
                return
            }

            guard httpResponse.statusCode == 200 else {
                let body = String(data: data, encoding: .utf8) ?? "No body"
                await MainActor.run {
                    chatState.addAssistantMessage("API error (\(httpResponse.statusCode)): \(body)")
                }
                return
            }

            // Parse Gemini response
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let candidates = json["candidates"] as? [[String: Any]],
               let firstCandidate = candidates.first,
               let content = firstCandidate["content"] as? [String: Any],
               let parts = content["parts"] as? [[String: Any]],
               let text = parts.first?["text"] as? String {
                await MainActor.run {
                    chatState.addAssistantMessage(text)
                }
            } else {
                await MainActor.run {
                    chatState.addAssistantMessage("Could not parse the AI response.")
                }
            }
        } catch {
            await MainActor.run {
                chatState.addAssistantMessage("Network error: \(error.localizedDescription)")
            }
        }
    }
}
