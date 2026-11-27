cmake_minimum_required(VERSION 3.20)
project(esport_match LANGUAGES CXX)

find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)
execute_process(COMMAND "${Python_EXECUTABLE}" -X utf8 -c "import nlohmann_json; print(nlohmann_json.get_include())"
                OUTPUT_VARIABLE MATCH_JSON_INCLUDE ENCODING UTF-8 OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
set(MATCH_CORE_SOURCES
    grid.cpp grid_round.cpp grid_turn.cpp match_state.cpp tick_output.cpp round_rules.cpp begin_live.cpp economy.cpp grenades.cpp combat.cpp objectives.cpp observation.cpp radio.cpp peer_feedback.cpp small_groups.cpp group_tasks.cpp group_selection.cpp group_peek.cpp
    opening.cpp defense_orders.cpp defense_opening.cpp team_ai.cpp reserves.cpp defense_review.cpp retake.cpp
    agent_turn.cpp individual_decision.cpp personal_turn.cpp agent_priority.cpp agent_survival.cpp contact.cpp spatial_intent.cpp sector.cpp postplant.cpp agent_utility.cpp crossing.cpp opening_execution.cpp tactic_execution.cpp
    navigation.cpp routes.cpp rays.cpp collision.cpp perception.cpp physical_navigation.cpp)
pybind11_add_module(_match_native module.cpp ray_bindings.cpp state_bindings.cpp ${MATCH_CORE_SOURCES})
target_include_directories(_match_native PRIVATE vendor/embree4 "${MATCH_JSON_INCLUDE}")
target_link_libraries(_match_native PRIVATE ${CMAKE_DL_LIBS})
target_compile_features(_match_native PRIVATE cxx_std_20)
set_target_properties(_match_native PROPERTIES CXX_EXTENSIONS OFF)
if(MSVC)
    target_compile_options(_match_native PRIVATE /fp:strict /utf-8)
else()
    target_compile_options(_match_native PRIVATE -ffp-contract=off)
endif()
install(TARGETS _match_native LIBRARY DESTINATION backend RUNTIME DESTINATION backend)

option(NAV_SANITIZERS "Run standalone geometry checks under ASan/LSan and UBSan" OFF)
if(NAV_SANITIZERS)
    enable_testing()
    add_executable(check_navigation navigation_checks.cpp navigation.cpp routes.cpp)
    target_compile_features(check_navigation PRIVATE cxx_std_20)
    target_compile_options(check_navigation PRIVATE -fsanitize=address,undefined -fno-sanitize-recover=all -ffp-contract=off)
    target_link_options(check_navigation PRIVATE -fsanitize=address,undefined)
    add_test(NAME navigation_sanitizers COMMAND check_navigation)
    add_executable(check_state state_checks.cpp ${MATCH_CORE_SOURCES})
    target_include_directories(check_state PRIVATE vendor/embree4 "${MATCH_JSON_INCLUDE}")
    target_link_libraries(check_state PRIVATE ${CMAKE_DL_LIBS})
    target_compile_features(check_state PRIVATE cxx_std_20)
    target_compile_options(check_state PRIVATE -fsanitize=address,undefined -fno-sanitize-recover=all -ffp-contract=off)
    target_link_options(check_state PRIVATE -fsanitize=address,undefined)
    execute_process(COMMAND "${Python_EXECUTABLE}" -c
        "import gzip,sys; sys.stdout.buffer.write(gzip.open(sys.argv[1], 'rb').read())"
        "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/r54/de_nuke.checkpoint.json.gz"
        OUTPUT_FILE "${CMAKE_CURRENT_BINARY_DIR}/nuke.json" COMMAND_ERROR_IS_FATAL ANY)
    add_test(NAME state_sanitizers COMMAND check_state "${CMAKE_CURRENT_BINARY_DIR}/nuke.json")
endif()

if(NAV_SANITIZERS AND EMBREE_TEST_LIBRARY)
    add_executable(check_rays ray_checks.cpp rays.cpp collision.cpp perception.cpp physical_navigation.cpp navigation.cpp routes.cpp)
    target_include_directories(check_rays PRIVATE vendor/embree4)
    target_link_libraries(check_rays PRIVATE ${CMAKE_DL_LIBS})
    target_compile_features(check_rays PRIVATE cxx_std_20)
    target_compile_options(check_rays PRIVATE -ffp-contract=off -fsanitize=address,undefined -fno-sanitize-recover=all)
    target_link_options(check_rays PRIVATE -fsanitize=address,undefined)
    add_test(NAME ray_sanitizers COMMAND check_rays "${EMBREE_TEST_LIBRARY}")
endif()
