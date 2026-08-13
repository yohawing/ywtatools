#include "quiet_output.h"

#include <geogram/basic/common.h>
#include <geogram/basic/logger.h>

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>

int main()
{
    GEO::initialize(GEO::GEOGRAM_INSTALL_HANDLERS);
    GEO::Logger::instance()->set_quiet(false);

    std::ostringstream captured;
    std::streambuf* original = std::cerr.rdbuf(captured.rdbuf());
    {
        ywta::autoremesher::ScopedQuietOutput quietOutput;
        std::cerr << "Extract edges..." << std::endl;
        std::cerr << "unexpected remesh failure" << std::endl;
        std::thread worker([]() { std::cerr << "worker diagnostic" << std::endl; });
        worker.join();
    }
    std::cerr.rdbuf(original);

    const std::string output = captured.str();
    if (output.find("Extract edges") != std::string::npos) {
        std::cerr << "known progress line was not suppressed\n";
        return EXIT_FAILURE;
    }
    if (output.find("unexpected remesh failure") == std::string::npos) {
        std::cerr << "unexpected error line was suppressed\n";
        return EXIT_FAILURE;
    }
    if (output.find("worker diagnostic") == std::string::npos) {
        std::cerr << "other thread output was suppressed\n";
        return EXIT_FAILURE;
    }
    if (GEO::Logger::instance()->is_quiet()) {
        std::cerr << "logger quiet state was not restored\n";
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
