.PHONY : clean

ec2-initialize: 
	perl make-ec2-initialize auth/development/worker.key | install -m 0755 /dev/stdin $@

clean:
	find . -type f \( -name '*~' -o -name '*.pyc' \) -delete
