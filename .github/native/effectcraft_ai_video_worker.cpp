#include "rife.h"
#include "realesrgan.h"
#include "cpu.h"
#include "gpu.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {
bool read_bytes(void* dst, size_t size) {
    return static_cast<bool>(std::cin.read(static_cast<char*>(dst), static_cast<std::streamsize>(size)));
}

template <typename T>
bool read_value(T& value) {
    return read_bytes(&value, sizeof(T));
}

template <typename T>
void write_value(const T& value) {
    std::cout.write(reinterpret_cast<const char*>(&value), sizeof(T));
}

void respond(int32_t status, uint32_t width = 0, uint32_t height = 0, const std::vector<uint8_t>* pixels = nullptr) {
    const uint64_t size = pixels ? static_cast<uint64_t>(pixels->size()) : 0;
    write_value(status);
    write_value(width);
    write_value(height);
    write_value(size);
    if (pixels && !pixels->empty()) {
        std::cout.write(reinterpret_cast<const char*>(pixels->data()), static_cast<std::streamsize>(pixels->size()));
    }
    std::cout.flush();
}

std::vector<uint8_t> rife_to_rgb(const ncnn::Mat& image) {
    const size_t size = static_cast<size_t>(image.w) * image.h * 3;
    std::vector<uint8_t> rgb(size);
    if (!image.data || image.w <= 0 || image.h <= 0) return {};
    // RIFE's process() writes packed RGB bytes into the caller-provided output buffer.
    std::memcpy(rgb.data(), image.data, size);
    return rgb;
}
} // namespace

int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    if (argc != 4) {
        respond(-1);
        return 2;
    }

    ncnn::create_gpu_instance();
    const int gpu_id = ncnn::get_gpu_count() > 0 ? 0 : -1;
    const int threads = std::max(1, std::min(2, ncnn::get_cpu_count()));

    {
    RIFE rife(gpu_id, false, false, false, threads, false, true);
    if (rife.load(std::string(argv[1])) != 0) {
        respond(-1);
        return 3;
    }

    RealESRGAN realesrgan(gpu_id, false);
    if (realesrgan.load(std::string(argv[2]), std::string(argv[3])) != 0) {
        respond(-1);
        return 4;
    }
    realesrgan.scale = 4;
    realesrgan.tilesize = gpu_id >= 0 ? 64 : 32;
    realesrgan.prepadding = 10;

    // Startup acknowledgement. No model is loaded from a network by this process.
    write_value(static_cast<int32_t>(0));
    std::cout.flush();

    for (;;) {
        uint32_t operation = 0;
        if (!read_value(operation)) break;

        uint32_t width = 0;
        uint32_t height = 0;
        float timestep = 0.f;
        if (!read_value(width) || !read_value(height) || !read_value(timestep)
            || width == 0 || height == 0 || width > 2048 || height > 2048) {
            respond(-1);
            break;
        }

        const uint64_t input_bytes = static_cast<uint64_t>(width) * height * 3;
        std::vector<uint8_t> first(static_cast<size_t>(input_bytes));
        if (!read_bytes(first.data(), first.size())) break;

        if (operation == 1) {
            std::vector<uint8_t> second(static_cast<size_t>(input_bytes));
            if (!read_bytes(second.data(), second.size())) break;
            ncnn::Mat in0(static_cast<int>(width), static_cast<int>(height), first.data(), static_cast<size_t>(3), 3);
            ncnn::Mat in1(static_cast<int>(width), static_cast<int>(height), second.data(), static_cast<size_t>(3), 3);
            // RIFE writes RGB bytes to an output buffer supplied by the caller.
            ncnn::Mat output(static_cast<int>(width), static_cast<int>(height), static_cast<size_t>(3), 3);
            const int result = rife.process(in0, in1, timestep, output);
            if (result != 0 || output.empty() || output.w != static_cast<int>(width) || output.h != static_cast<int>(height) || output.c < 3) {
                respond(-1);
                continue;
            }
            const auto rgb = rife_to_rgb(output);
            respond(0, width, height, &rgb);
        } else if (operation == 2) {
            ncnn::Mat input(static_cast<int>(width), static_cast<int>(height), first.data(), static_cast<size_t>(3), 3);
            const uint32_t out_width = width * static_cast<uint32_t>(realesrgan.scale);
            const uint32_t out_height = height * static_cast<uint32_t>(realesrgan.scale);
            if (out_width > 8192 || out_height > 8192) {
                respond(-1);
                continue;
            }
            ncnn::Mat output(static_cast<int>(out_width), static_cast<int>(out_height), static_cast<size_t>(3), 3);
            const int result = realesrgan.process(input, output);
            if (result != 0 || output.empty()) {
                respond(-1);
                continue;
            }
            const size_t size = static_cast<size_t>(out_width) * out_height * 3;
            std::vector<uint8_t> rgb(size);
            std::memcpy(rgb.data(), output.data, size);
            respond(0, out_width, out_height, &rgb);
        } else {
            respond(-1);
        }
    }

    }
    ncnn::destroy_gpu_instance();
    return 0;
}
