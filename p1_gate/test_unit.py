import os
import tempfile
import unittest
from pathlib import Path
from node_agent import Agent, Cache, DockerRuntime, Instance, Limits


class Client:
    def __init__(self, desired): self.desired=desired; self.down=False; self.status=[]
    def desired_state(self):
        if self.down: raise OSError('control plane down')
        return self.desired
    def report_status(self, status): self.status=status


class Runtime:
    def __init__(self): self.running=set(); self.starts=0
    def ensure_running(self, item):
        if item.id not in self.running: self.starts += 1
        self.running.add(item.id)
        return 'cid-'+item.id
    def ensure_stopped(self, item): self.running.discard(item.id)


def inst(state='running'):
    return Instance('i1','o1','e1','python:3.12-alpine',state,('python','-V'),Limits(.25,128,64),1)


class Tests(unittest.TestCase):
    def test_limits(self):
        with self.assertRaises(ValueError): Limits(99,128,64)
    def test_command_must_be_argv(self):
        with self.assertRaises(ValueError): Instance.from_dict({'id':'i','org_id':'o','env_id':'e','image':'x','command':'sh -c x'})
    def test_env_network_isolation(self):
        a=Instance('a','o','e1','x'); b=Instance('b','o','e2','x')
        self.assertNotEqual(a.network_name,b.network_name)
    def test_cache_0600(self):
        with tempfile.TemporaryDirectory() as d:
            c=Cache(Path(d)/'state.json'); c.save([inst()])
            self.assertEqual(os.stat(c.path).st_mode & 0o777,0o600)
            self.assertEqual(c.load()[0].id,'i1')
    def test_start(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client([inst()]); r=Runtime(); Agent(c,Cache(Path(d)/'s'),r).tick()
            self.assertIn('i1',r.running)
    def test_kill_is_reconciled(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client([inst()]); r=Runtime(); a=Agent(c,Cache(Path(d)/'s'),r)
            a.tick(); r.running.clear(); a.tick(); self.assertEqual(r.starts,2)
    def test_cp_outage_uses_cache(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client([inst()]); r=Runtime(); a=Agent(c,Cache(Path(d)/'s'),r)
            a.tick(); c.down=True; r.running.clear(); self.assertFalse(a.tick()); self.assertIn('i1',r.running)
    def test_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            c=Client([inst('stopped')]); r=Runtime(); r.running.add('i1'); Agent(c,Cache(Path(d)/'s'),r).tick(); self.assertNotIn('i1',r.running)
    def test_dns_servers_must_be_public(self):
        self.assertEqual(DockerRuntime('n').dns_servers, ('1.1.1.1','8.8.8.8'))
        with self.assertRaises(ValueError): DockerRuntime('n', dns_servers=('10.0.0.53',))
    def test_runtime_source_forbids_unsafe_flags(self):
        src=Path(__file__).with_name('node_agent.py').read_text()
        self.assertIn('--runtime=runsc',src); self.assertIn('--read-only',src); self.assertIn('--cap-drop=ALL',src); self.assertIn('--dns',src)
        for bad in ('--privileged','--network=host','--pid=host','/var/run/docker.sock'):
            self.assertNotIn(bad,src)


if __name__ == '__main__': unittest.main(verbosity=2)
