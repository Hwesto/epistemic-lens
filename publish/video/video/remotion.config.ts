import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
// Headless Chrome flags useful in containers / CI
Config.setChromiumOpenGlRenderer("angle");
Config.setBrowserExecutable(null); // let Remotion fetch its own Chromium
Config.setConcurrency(2);
