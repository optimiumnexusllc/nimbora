import { configure } from "@testing-library/react";

// CI runners are slower than a laptop: the first render of the app (lazy
// modules, fake SIP stack) can take more than the default 1 s of findBy*.
configure({ asyncUtilTimeout: 5000 });
