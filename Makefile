.PHONY : clean

ec2-initialize-development:: 
	perl make-ec2-initialize auth/development/worker.key development | install -m 0755 /dev/stdin $@

ec2-initialize-production::
	perl make-ec2-initialize auth/production/worker.key production | install -m 0755 /dev/stdin $@

clean:
	find . -type f \( -name '*~' -o -name '*.pyc' \) -delete
