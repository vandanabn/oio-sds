add_definitions(-DG_LOG_DOMAIN="oio.events")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Werror")

include_directories(BEFORE
		${CMAKE_SOURCE_DIR}
		${CMAKE_CURRENT_SOURCE_DIR}
		${CMAKE_CURRENT_BINARY_DIR}
		${CMAKE_BINARY_DIR}
		${CMAKE_BINARY_DIR}/metautils/lib)

add_custom_command(
	OUTPUT
		${CMAKE_CURRENT_BINARY_DIR}/events_variables.c
		${CMAKE_CURRENT_BINARY_DIR}/events_variables.h
	DEPENDS
		${CMAKE_SOURCE_DIR}/confgen.py
		${CMAKE_SOURCE_DIR}/conf.json
	PRE_BUILD
	COMMENT
		"Generating the central configuration"
	COMMAND
		${PYTHON_EXECUTABLE}
	ARGS
		${CMAKE_SOURCE_DIR}/confgen.py
		"events"
		${CMAKE_SOURCE_DIR}/conf.json)

add_library(oioevents SHARED
	oio_events_queue.c
	oio_events_queue_buffer.c
	oio_events_queue_internals.c
	oio_events_queue_fanout.c
	oio_events_queue_beanstalkd.c
	${CMAKE_CURRENT_BINARY_DIR}/events_variables.c)

set_target_properties(oioevents PROPERTIES VERSION 0.0.0 SOVERSION 0)
target_link_libraries(oioevents metautils ${GLIB2_LIBRARIES})

install(TARGETS oioevents
		LIBRARY DESTINATION ${LD_LIBDIR}
		RUNTIME DESTINATION bin
		PUBLIC_HEADER DESTINATION include)


