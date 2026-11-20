declare const _default: {
    demo: {
        date: string;
        seed: number;
    };
    shots: ({
        name: string;
        route: string;
        alt: string;
        waitForFn: string;
        actions: ({
            click: string;
            waitFor?: undefined;
            scroll?: undefined;
        } | {
            click?: undefined;
            waitFor: string;
            scroll?: undefined;
        } | {
            click?: undefined;
            waitFor?: undefined;
            scroll: {
                y: number;
            };
        })[];
        viewport: {
            width: number;
            height: number;
            deviceScaleFactor: number;
        };
        themes: "light"[];
        readme: "hero";
        featured: true;
    } | {
        actions?: undefined;
        name: string;
        route: string;
        alt: string;
        waitForFn: string;
        viewport: {
            width: number;
            height: number;
            deviceScaleFactor: number;
        };
        themes: "light"[];
        readme: "feature";
        featured: true;
    } | {
        actions?: undefined;
        viewport?: undefined;
        featured?: undefined;
        name: string;
        route: string;
        alt: string;
        waitForFn: string;
        themes: "light"[];
        readme: "feature";
    })[];
};
export default _default;
