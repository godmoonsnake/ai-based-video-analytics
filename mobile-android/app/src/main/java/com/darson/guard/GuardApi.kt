package com.darson.guard

import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import org.json.JSONArray
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class ApiFailure(val status: Int, message: String) : Exception(message)

/** HTTPS-only client. Every request obtains a fresh bearer token from AppAuth. */
class GuardApi(private val token: ((String?, Exception?) -> Unit) -> Unit) {
    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val base = BuildConfig.API_BASE.trimEnd('/')

    init { require(base.startsWith("https://")) { "DARSON_API_BASE must use HTTPS" } }

    fun json(
        method: String, path: String, body: JSONObject? = null,
        done: (JSONObject?, Exception?) -> Unit
    ) = request(method, path, body, 1_000_000) { bytes, error ->
        if (error != null) done(null, error)
        else try { done(JSONObject(String(bytes ?: ByteArray(0), Charsets.UTF_8)), null) }
        catch (exception: Exception) { done(null, exception) }
    }

    fun bytes(path: String, done: (ByteArray?, Exception?) -> Unit) =
        request("GET", path, null, 8_000_000, done)

    fun array(path: String, done: (JSONArray?, Exception?) -> Unit) =
        request("GET", path, null, 1_000_000) { bytes, error ->
            if (error != null) done(null, error)
            else try { done(JSONArray(String(bytes ?: ByteArray(0), Charsets.UTF_8)), null) }
            catch (exception: Exception) { done(null, exception) }
        }

    private fun request(
        method: String, path: String, body: JSONObject?, limit: Int,
        done: (ByteArray?, Exception?) -> Unit
    ) {
        if (!path.startsWith("/") || path.startsWith("//")) {
            done(null, IllegalArgumentException("Invalid API path")); return
        }
        token { bearer, authError ->
            if (authError != null || bearer == null) {
                done(null, authError ?: ApiFailure(401, "Sign in again"))
                return@token
            }
            executor.execute {
                var connection: HttpURLConnection? = null
                try {
                    connection = URL(base + path).openConnection() as HttpURLConnection
                    connection.requestMethod = method
                    connection.connectTimeout = 8000
                    connection.readTimeout = 10000
                    connection.setRequestProperty("Authorization", "Bearer $bearer")
                    connection.setRequestProperty("Accept", "application/json, image/jpeg, image/png")
                    connection.setRequestProperty("Cache-Control", "no-store")
                    if (body != null) {
                        connection.doOutput = true
                        connection.setRequestProperty("Content-Type", "application/json")
                        connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                    }
                    val status = connection.responseCode
                    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                    val output = ByteArrayOutputStream()
                    stream?.use { input ->
                        val buffer = ByteArray(8192)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            if (output.size() + count > limit) throw ApiFailure(413, "Evidence is too large for the phone")
                            output.write(buffer, 0, count)
                        }
                    }
                    val bytes = output.toByteArray()
                    if (status !in 200..299) {
                        val detail = try { JSONObject(String(bytes)).optString("detail") }
                        catch (_: Exception) { "Request failed" }
                        throw ApiFailure(status, detail.ifBlank { "Request failed ($status)" })
                    }
                    main.post { done(bytes, null) }
                } catch (exception: Exception) {
                    main.post { done(null, exception) }
                } finally { connection?.disconnect() }
            }
        }
    }
}
