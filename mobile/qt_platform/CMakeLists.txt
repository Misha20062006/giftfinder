cmake_minimum_required(VERSION 3.22)
project(GiftFinderQtAndroidPlatform LANGUAGES C CXX)

# Build the exact Qt 6.12 Android platform sources against its SDK headers and
# the pinned PySide wheel's actual Core/Gui libraries. The two-line accessibility
# change is applied and hash-verified before configuration.
find_package(Qt6 6.12.0 EXACT REQUIRED COMPONENTS Core Gui CorePrivate GuiPrivate)
set(CMAKE_AUTOMOC ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(platform "${GIFTFINDER_QTBASE_SOURCE}/src/plugins/platforms/android")
set(sources
    androidcontentfileengine.cpp qandroidapkfileengine.cpp androidjniinput.cpp
    androidjnimain.cpp androidjnimenu.cpp main.cpp qandroidassetsfileenginehandler.cpp
    qandroideventdispatcher.cpp qandroidinputcontext.cpp qandroidplatformdialoghelpers.cpp
    qandroidplatformfiledialoghelper.cpp qandroidplatformfontdatabase.cpp
    qandroidplatformforeignwindow.cpp qandroidplatformfileiconengine.cpp
    qandroidplatformiconengine.cpp qandroidplatformintegration.cpp qandroidplatformmenu.cpp
    qandroidplatformmenubar.cpp qandroidplatformmenuitem.cpp qandroidplatformscreen.cpp
    qandroidplatformservices.cpp qandroidplatformtheme.cpp qandroidplatformwindow.cpp
    androidwindowembedding.cpp androidbackendregister.cpp)
if(QT_FEATURE_android_style_assets)
    list(APPEND sources extract.cpp)
else()
    list(APPEND sources extract-dummy.cpp)
endif()
if(QT_FEATURE_clipboard)
    list(APPEND sources qandroidplatformclipboard.cpp)
endif()
if(QT_FEATURE_draganddrop)
    list(APPEND sources qandroidplatformdrag.cpp)
endif()
if(QT_FEATURE_accessibility)
    list(APPEND sources androidjniaccessibility.cpp qandroidplatformaccessibility.cpp)
else()
    message(FATAL_ERROR "The Android release requires Qt accessibility")
endif()
if(QT_FEATURE_egl)
    list(APPEND sources qandroidplatformopenglcontext.cpp qandroidplatformopenglwindow.cpp
         qandroidplatformoffscreensurface.cpp)
endif()
if(QT_FEATURE_vulkan)
    list(APPEND sources qandroidplatformvulkaninstance.cpp qandroidplatformvulkanwindow.cpp)
endif()
list(TRANSFORM sources PREPEND "${platform}/")
file(GLOB headers "${platform}/*.h")
qt_add_plugin(GiftFinderQtAndroidPlatform SHARED CLASS_NAME QAndroidIntegrationPlugin
    PLUGIN_TYPE platforms OUTPUT_NAME qtforandroid ${sources} ${headers})
set_target_properties(GiftFinderQtAndroidPlatform PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}")
target_include_directories(GiftFinderQtAndroidPlatform PRIVATE "${platform}"
    "${GIFTFINDER_QTBASE_SOURCE}/src/3rdparty/android")
target_link_libraries(GiftFinderQtAndroidPlatform PRIVATE
    Qt6::Core Qt6::CorePrivate Qt6::Gui Qt6::GuiPrivate Qt6::PlatformPluginInternal
    android jnigraphics)
if(QT_FEATURE_egl)
    target_link_libraries(GiftFinderQtAndroidPlatform PRIVATE EGL)
endif()
target_link_options(GiftFinderQtAndroidPlatform PRIVATE
    "-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384"
    "-Wl,-z,relro" "-Wl,-z,now" "-Wl,--no-undefined")
