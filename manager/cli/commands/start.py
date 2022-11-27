from manager.cli.cli import CLICommand
from manager.constants import logger


class Start(CLICommand):
    doc = """Start instances that match the arguments."""
    args_optional = ["query"]
    flags = ["-a", "-s", "-y"]

    @staticmethod
    def run(cli):
        silent = cli.flags.get("silent", False)

        logger.info("Looking for stopped instances...")

        instances_to_start = cli.get_instances_for_action(
            lambda i: not i.is_running())
        if len(instances_to_start) == 0:
            return

        if cli.confirm_action("start", instances_to_start) != True:
            return

        logger.info("Starting instances...")
        started_instances = []
        failed = []
        for instance in instances_to_start:
            started = instance.start(silent)
            if started:
                started_instances.append(instance.get_id())
            else:
                failed.append(instance.get_id())

        logger.info("Started {} instance(s)".format(len(started_instances)))

        if len(failed) > 0:
            logger.info("Failed to start {} instances:".format(len(failed)))
            for id in failed:
                logger.info("- {}".format(id))
