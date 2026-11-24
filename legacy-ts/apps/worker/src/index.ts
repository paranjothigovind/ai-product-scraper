import { loadEnv } from "@scraper/core";
import { pino } from "pino";

const logger = pino({ level: "info" });
const env = loadEnv();

// TODO(next): BullMQ consumer + graph runner (phase 5).
logger.info({ maxPagesTotal: env.MAX_PAGES_TOTAL }, "worker config validated");
